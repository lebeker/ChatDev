import atexit
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from server.settings import WARE_HOUSE_DIR
from server.state import get_websocket_manager
from utils.exceptions import ResourceNotFoundError, ValidationError
from utils.structured_logger import get_server_logger, LogType

router = APIRouter()


@router.get("/api/sessions")
async def list_sessions(yaml_file: Optional[str] = None):
    """List all available sessions (from disk and in-memory).
    
    Args:
        yaml_file: Optional filter to only return sessions for a specific workflow template
    """
    try:
        sessions = []
        
        # Get in-memory sessions
        manager = get_websocket_manager()
        in_memory_sessions = manager.session_store.list_sessions()
        
        # Get sessions from disk
        if WARE_HOUSE_DIR.exists():
            for session_dir in WARE_HOUSE_DIR.iterdir():
                if session_dir.is_dir() and session_dir.name.startswith("session_"):
                    session_id = session_dir.name.replace("session_", "")
                    
                    # Check if already in in-memory (will use that data)
                    if session_id in in_memory_sessions:
                        session_info = in_memory_sessions[session_id]
                        session_obj = manager.session_store.get_session(session_id)
                        sessions.append({
                            "session_id": session_id,
                            "yaml_file": session_info.get("yaml_file", ""),
                            "status": session_info.get("status", "unknown"),
                            "created_at": session_info.get("created_at", 0),
                            "updated_at": session_info.get("updated_at", 0),
                            "task_prompt": session_obj.task_prompt if session_obj else "",
                            "has_directory": True,
                        })
                    else:
                        # Session exists on disk but not in memory
                        # Try to read metadata if available
                        metadata_file = session_dir / "metadata.json"
                        metadata = {}
                        if metadata_file.exists():
                            try:
                                metadata = json.loads(metadata_file.read_text())
                            except Exception:
                                pass
                        
                        # Try to extract yaml_file from various sources
                        yaml_file = metadata.get("yaml_file", "")
                        
                        # Check execution_logs.json for yaml_file and task_prompt
                        execution_logs_file = session_dir / "execution_logs.json"
                        has_completion = False
                        last_task_prompt = metadata.get("task_prompt", "")
                        
                        if execution_logs_file.exists():
                            try:
                                logs_data = json.loads(execution_logs_file.read_text())
                                if isinstance(logs_data, dict):
                                    logs = logs_data.get("logs", [])
                                    summary = logs_data.get("summary", {})
                                    
                                    # Extract yaml_file from summary
                                    if not yaml_file and "workflow_id" in summary:
                                        # workflow_id might contain yaml info
                                        workflow_id = summary.get("workflow_id", "")
                                        if workflow_id:
                                            yaml_file = workflow_id
                                    
                                    if isinstance(logs, list):
                                        # Look for completion messages and extract info
                                        for log_entry in logs:
                                            if not isinstance(log_entry, dict):
                                                continue
                                            
                                            event_type = log_entry.get("event_type")
                                            message = log_entry.get("message", "")
                                            details = log_entry.get("details", {})
                                            
                                            # Check for completion indicators
                                            if event_type == "WORKFLOW_COMPLETED" or "workflow_completed" in str(message).lower() or "completed successfully" in str(message).lower():
                                                has_completion = True
                                            
                                            # Extract yaml_file from details
                                            if not yaml_file:
                                                if "yaml_file" in details:
                                                    yaml_file = details["yaml_file"]
                                                elif "yaml" in details:
                                                    yaml_file = details["yaml"]
                                            
                                            # Extract task prompt from logs
                                            if not last_task_prompt:
                                                if "task_prompt" in details:
                                                    last_task_prompt = details["task_prompt"]
                                                elif "task" in details:
                                                    last_task_prompt = details["task"]
                                                elif "input" in details:
                                                    last_task_prompt = details["input"]
                            except Exception:
                                pass
                        
                        # Check for yaml_file in code_workspace directory name or files
                        if not yaml_file:
                            code_workspace = session_dir / "code_workspace"
                            if code_workspace.exists():
                                # Look for any .yaml files that might indicate the workflow
                                for yaml_file_path in session_dir.rglob("*.yaml"):
                                    yaml_name = yaml_file_path.name
                                    # Skip if it's a result file
                                    if "workflow_summary" not in yaml_name and "node_outputs" not in yaml_name:
                                        yaml_file = yaml_name
                                        break
                        
                        # Detect actual status
                        actual_status = metadata.get("status", "completed")
                        if actual_status == "completed" and not has_completion:
                            actual_status = "terminated"
                        
                        # Get directory size
                        try:
                            total_size = sum(f.stat().st_size for f in session_dir.rglob('*') if f.is_file())
                        except Exception:
                            total_size = 0
                        
                        sessions.append({
                            "session_id": session_id,
                            "yaml_file": yaml_file,
                            "status": actual_status,
                            "created_at": metadata.get("created_at", session_dir.stat().st_mtime),
                            "updated_at": metadata.get("updated_at", session_dir.stat().st_mtime),
                            "task_prompt": last_task_prompt or metadata.get("task_prompt", ""),
                            "has_directory": True,
                            "size": total_size,
                            "can_resume": actual_status == "terminated",
                        })
        
        # Filter by yaml_file if provided
        if yaml_file:
            sessions = [s for s in sessions if s.get("yaml_file") == yaml_file]
        
        # Sort by updated_at descending (most recent first)
        sessions.sort(key=lambda x: x.get("updated_at", 0), reverse=True)
        
        return {"sessions": sessions}
    except Exception as exc:
        logger = get_server_logger()
        logger.log_exception(exc, "Failed to list sessions")
        raise HTTPException(status_code=500, detail="Failed to list sessions")


@router.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """Get session details including metadata and chat history."""
    try:
        if not re.match(r"^[a-zA-Z0-9_-]+$", session_id):
            raise ValidationError(
                "Invalid session_id: only letters, digits, underscores, and hyphens are allowed",
                field="session_id",
            )
        
        manager = get_websocket_manager()
        
        # Try to get from in-memory store first
        session_info = manager.session_store.get_session_info(session_id)
        
        # Check if session directory exists
        dir_name = f"session_{session_id}"
        session_path = WARE_HOUSE_DIR / dir_name
        
        if not session_path.exists() or not session_path.is_dir():
            if not session_info:
                raise ResourceNotFoundError(
                    "Session not found",
                    resource_type="session",
                    resource_id=session_id,
                )
        
        # Try to load chat history from logs
        chat_history = []
        has_completion = False
        last_task_prompt = ""
        
        # First try execution_logs.json (main log file)
        execution_logs_file = session_path / "execution_logs.json"
        if execution_logs_file.exists():
            try:
                logs_data = json.loads(execution_logs_file.read_text())
                if isinstance(logs_data, dict):
                    logs = logs_data.get("logs", [])
                    if isinstance(logs, list):
                        for log_entry in logs:
                            if not isinstance(log_entry, dict):
                                continue
                            
                            event_type = log_entry.get("event_type")
                            node_id = log_entry.get("node_id", "")
                            message = log_entry.get("message", "")
                            details = log_entry.get("details", {})
                            timestamp = log_entry.get("timestamp", "")
                            
                            # Check for completion
                            if event_type == "WORKFLOW_COMPLETED" or "workflow_completed" in str(message).lower() or "completed successfully" in str(message).lower():
                                has_completion = True
                            
                            # Extract task prompt
                            if not last_task_prompt:
                                if "task_prompt" in details:
                                    last_task_prompt = details["task_prompt"]
                                elif "task" in details:
                                    last_task_prompt = details["task"]
                            
                            # Extract dialogue messages
                            if event_type == "NODE_START" and message and node_id:
                                chat_history.append({
                                    "type": "dialogue",
                                    "name": node_id,
                                    "text": f"Starting: {message}",
                                    "timestamp": timestamp,
                                })
                            elif event_type == "NODE_END" and node_id:
                                output = details.get("output", message)
                                if output:
                                    chat_history.append({
                                        "type": "dialogue",
                                        "name": node_id,
                                        "text": str(output),
                                        "timestamp": timestamp,
                                    })
                            elif message and node_id and event_type not in ["WORKFLOW_START", "WORKFLOW_COMPLETED"]:
                                # Other meaningful messages
                                chat_history.append({
                                    "type": "dialogue",
                                    "name": node_id,
                                    "text": message,
                                    "timestamp": timestamp,
                                })
            except Exception:
                pass
        
        # Also check logs directory for JSONL files
        logs_dir = session_path / "logs"
        if logs_dir.exists():
            for log_file in sorted(logs_dir.glob("*.jsonl"), reverse=True):
                try:
                    with open(log_file, 'r') as f:
                        for line in f:
                            try:
                                log_entry = json.loads(line.strip())
                                if log_entry.get("log_type") == "workflow":
                                    event_type = log_entry.get("event_type")
                                    node_id = log_entry.get("node_id", "")
                                    message = log_entry.get("message", "")
                                    if message and node_id and event_type in ["NODE_START", "NODE_END"]:
                                        # Avoid duplicates
                                        if not any(h.get("text") == message and h.get("name") == node_id for h in chat_history):
                                            chat_history.append({
                                                "type": "dialogue",
                                                "name": node_id,
                                                "text": message,
                                                "timestamp": log_entry.get("timestamp", ""),
                                            })
                            except json.JSONDecodeError:
                                continue
                except Exception:
                    continue
        
        # If we have in-memory session info, use it
        if session_info:
            session_obj = manager.session_store.get_session(session_id)
            status_from_info = session_info.get("status", "unknown")
            # Check if session can be resumed (terminated or in error state but not cancelled)
            can_resume = status_from_info in ["terminated", "error"] or (
                status_from_info == "completed" and not has_completion
            )
            return {
                "session_id": session_id,
                "yaml_file": session_info.get("yaml_file", ""),
                "status": status_from_info if status_from_info != "completed" or has_completion else "terminated",
                "created_at": session_info.get("created_at", 0),
                "updated_at": session_info.get("updated_at", 0),
                "task_prompt": session_obj.task_prompt if session_obj else "",
                "chat_history": chat_history,
                "has_directory": session_path.exists(),
                "can_resume": can_resume,
            }
        
        # Otherwise return disk-based info
        metadata_file = session_path / "metadata.json"
        metadata = {}
        if metadata_file.exists():
            try:
                metadata = json.loads(metadata_file.read_text())
            except Exception:
                pass
        
        # Try to extract yaml_file from various sources if not in metadata
        yaml_file = metadata.get("yaml_file", "")
        if not yaml_file:
            # Check execution_logs.json summary
            if execution_logs_file.exists():
                try:
                    logs_data = json.loads(execution_logs_file.read_text())
                    if isinstance(logs_data, dict):
                        summary = logs_data.get("summary", {})
                        workflow_id = summary.get("workflow_id", "")
                        if workflow_id:
                            yaml_file = workflow_id
                except Exception:
                    pass
            
            # Check code_workspace for yaml files
            if not yaml_file:
                code_workspace = session_path / "code_workspace"
                if code_workspace.exists():
                    for yaml_file_path in session_path.rglob("*.yaml"):
                        yaml_name = yaml_file_path.name
                        if "workflow_summary" not in yaml_name and "node_outputs" not in yaml_name:
                            yaml_file = yaml_name
                            break
        
        # Determine actual status
        status_from_metadata = metadata.get("status", "completed")
        actual_status = status_from_metadata
        if status_from_metadata == "completed" and not has_completion:
            actual_status = "terminated"
        
        # Use task prompt from logs if available, otherwise from metadata
        final_task_prompt = last_task_prompt or metadata.get("task_prompt", "")
        
        return {
            "session_id": session_id,
            "yaml_file": yaml_file,
            "status": actual_status,
            "created_at": metadata.get("created_at", session_path.stat().st_mtime),
            "updated_at": metadata.get("updated_at", session_path.stat().st_mtime),
            "task_prompt": final_task_prompt,
            "chat_history": chat_history,
            "has_directory": True,
            "can_resume": actual_status == "terminated",
        }
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as exc:
        logger = get_server_logger()
        logger.log_exception(exc, f"Failed to get session: {session_id}")
        raise HTTPException(status_code=500, detail="Failed to get session")


@router.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a session and its directory."""
    try:
        if not re.match(r"^[a-zA-Z0-9_-]+$", session_id):
            raise ValidationError(
                "Invalid session_id: only letters, digits, underscores, and hyphens are allowed",
                field="session_id",
            )
        
        manager = get_websocket_manager()
        
        # Cancel if running
        if manager.session_store.has_session(session_id):
            manager.workflow_run_service.request_cancel(session_id, reason="Session deletion requested")
            manager.session_store.pop_session(session_id)
            manager.session_controller.cleanup_session(session_id)
            manager.attachment_service.cleanup_session(session_id)
        
        # Delete directory
        dir_name = f"session_{session_id}"
        session_path = WARE_HOUSE_DIR / dir_name
        
        if session_path.exists() and session_path.is_dir():
            shutil.rmtree(session_path, ignore_errors=True)
            logger = get_server_logger()
            logger.info(
                "Session deleted",
                log_type=LogType.WORKFLOW,
                session_id=session_id,
            )
        
        return {"status": "deleted", "session_id": session_id}
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger = get_server_logger()
        logger.log_exception(exc, f"Failed to delete session: {session_id}")
        raise HTTPException(status_code=500, detail="Failed to delete session")


@router.get("/api/sessions/{session_id}/download")
async def download_session(session_id: str):
    try:
        if not re.match(r"^[a-zA-Z0-9_-]+$", session_id):
            logger = get_server_logger()
            logger.log_security_event(
                "INVALID_SESSION_ID_FORMAT",
                f"Invalid session_id format: {session_id}",
                details={"received_session_id": session_id},
            )
            raise ValidationError(
                "Invalid session_id: only letters, digits, underscores, and hyphens are allowed",
                field="session_id",
            )

        dir_name = f"session_{session_id}"
        session_path = WARE_HOUSE_DIR / dir_name

        if not session_path.exists() or not session_path.is_dir():
            raise ResourceNotFoundError(
                "Session directory not found",
                resource_type="session",
                resource_id=session_id,
            )

        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp_file:
            zip_path = Path(tmp_file.name)

        archive_base = zip_path.with_suffix("")
        try:
            shutil.make_archive(str(archive_base), "zip", root_dir=WARE_HOUSE_DIR, base_dir=dir_name)
        except Exception as exc:
            if zip_path.exists():
                zip_path.unlink()
            logger = get_server_logger()
            logger.log_exception(exc, f"Failed to create zip archive for session: {session_id}")
            raise HTTPException(status_code=500, detail="Failed to create zip archive")

        logger = get_server_logger()
        logger.info(
            "Session download prepared",
            log_type=LogType.WORKFLOW,
            session_id=session_id,
            archive_path=str(zip_path),
        )

        def cleanup_zip():
            if zip_path.exists():
                zip_path.unlink()

        atexit.register(cleanup_zip)

        return FileResponse(
            path=zip_path,
            filename=f"{dir_name}.zip",
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={dir_name}.zip"},
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Session directory not found")
    except HTTPException:
        raise
    except Exception as exc:
        logger = get_server_logger()
        logger.log_exception(exc, f"Unexpected error during session download: {session_id}")
        raise HTTPException(status_code=500, detail="Failed to download session")
