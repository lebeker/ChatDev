"""WebSocket endpoint routing."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from server.state import get_websocket_manager

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    manager = get_websocket_manager()
    # Get session_id from query parameters if provided
    session_id = websocket.query_params.get("session_id")
    # Use provided session_id or create new one
    connected_session_id = await manager.connect(websocket, session_id=session_id)
    try:
        while True:
            message = await websocket.receive_text()
            await manager.handle_message(connected_session_id, message)
    except WebSocketDisconnect:
        manager.disconnect(connected_session_id)
