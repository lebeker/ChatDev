# ChatDev — Consolidated issues and tasks

> Derived from session `session_cd13c0a5-ea51-41c3-a26d-ed25646a1a3c` (Xonix game) and general workflow requirements.

---

## Summary

| # | Category | Issue | Priority |
|---|----------|--------|----------|
| 1 | Tools | ~~`uv_run`: agent passes both `module` and `script` → "Provide exactly one of module or script"~~ | High |
| 2 | Tools / Content | ~~`save_file`: literal `\n` written to files → SyntaxError in Python~~ | High |
| 3 | Tools / Workflow | ~~No multi-file support: agents can't create/edit multiple files in one go~~ | High |
| 4 | Deliverable | ~~Wrong output: Snake implementations + empty files instead of Xonix~~ | High |
| 5 | Observability / Resilience | ~~Logs written only at workflow end → no pause/resume on abrupt stop~~ | High |
| 6 | Workflow | ~~Manual phase loop limit (1) too low for complex apps~~ | Medium |
| 7 | Environment | ~~Venv Python 3.10 vs project `requires-python` 3.12~~ | Medium |
| 8 | Environment | ~~UV hardlink warning (cosmetic)~~ | Low |

---

## 1. Tools

### 1.1 `uv_run`: enforce "exactly one of module or script" ✅

- **What:** Backend requires either `module` or `script`, not both. Agents repeatedly send both (e.g. `module: "main"`, `script: "main.py"`), causing 3 tool errors in one session.
- **Where:** Tool schema (e.g. design YAML / tool spec) and/or executor that runs `uv run`.
- **Relation to §1.3 (multi-file):** Not the same issue — `uv_run` is "run one entrypoint"; multi-file is "create/edit many files." They are related: both improve with **project awareness**. If the workflow has an explicit entrypoint (e.g. "main script: main.py") or a higher-level "run project" that infers it from the project, the agent need not choose module vs script at all. Consider addressing 1.1 and 1.3 together (e.g. design-phase output that sets entrypoint + schema/validation for uv_run).
- **Tasks:**
  - [x] Make schema explicit: "Provide exactly one of `module` or `script`; mutually exclusive."
  - [x] Validate in executor: reject or normalize when both are set (e.g. prefer `script` when both present, or return clear error).
  - [ ] Optionally add oneOf in schema if the stack supports it.
  - [ ] (Optional, with §1.3) Add project-aware run: e.g. "run project" using design/entrypoint so agent doesn't pick module vs script.

### 1.2 `save_file`: avoid literal `\n` in file content ✅

- **What:** Agent-provided content sometimes contains literal backslash-n instead of newlines (e.g. entire `main.py` on one line with `\n`), causing SyntaxError.
- **Where:** Path from agent payload → `save_file` implementation → disk write.
- **Tasks:**
  - [x] Decide policy: never interpret `\n` as newline in content (agent must send real newlines), or support optional "unescape" for tool input.
  - [x] Document expected format for multi-line content in tool description.
  - [ ] Add tests: multi-line Python file via `save_file` results in valid source (no literal `\n`).

### 1.3 Multi-file workflows: tools and prompts ✅

- **What:** Workflows that build "complex applications" often need creating/editing many files. Current tooling is oriented toward single-file operations; agents struggle to work with multiple files effectively.
- **Where:** Tool catalog (e.g. `save_file`, `apply_text_edits`, `read_file_segment`), and possibly prompts that steer batching.
- **Relation to §1.1 (uv_run):** Clear project structure (list of files, single entrypoint) can reduce `uv_run` misuse: agent knows "run main.py" instead of guessing both module and script. When adding project/file-plan output (§2.1), consider including the run entrypoint so 1.1 and 1.3 fixes align.
- **Tasks:**
  - [x] Audit existing tools: which already support multiple paths or batch operations (e.g. list of edits, list of files)?
  - [x] Consider new tools or overloads, e.g.:
    - Batch save: accept multiple `{ path, content }` in one call.
    - Batch read: accept multiple paths and return multiple snippets.
    - "Plan files" / "list files to create": optional step so the agent commits to a file set before editing.
  - [ ] Update agent instructions (design/prompts) to prefer batching when available and to plan multi-file structure (e.g. "list files you will create, then create them").

---

## 2. Deliverable quality

### 2.1 Wrong game + unused files (Snake vs Xonix, empty files) ✅

- **What:** Task was "simple but catchy implementation of a Xonix game." Result included two Snake-like implementations and three empty (or irrelevant) files instead of a single, clear Xonix implementation.
- **Where:** Task interpretation, design phase, and coding phases (Programmer Coding, Code Complete, etc.).
- **Tasks:**
  - [x] Strengthen task/design handoff: explicit "deliverable" (e.g. "one Xonix game, entrypoint X") in prompt or design artifact.
  - [x] Add validation or checklist step: "Does the codebase match the requested deliverable (Xonix, not Snake)? List created files and their roles."
  - [x] Consider design-phase output: e.g. required files and one-sentence purpose (e.g. "main.py: Xonix entrypoint").
  - [x] Optionally add a "cleanup unused files" or "remove placeholder files" instruction for the final phase.

---

## 3. Observability and resilience

### 3.1 Logs only at workflow end → no pause/resume ✅

- **What:** Execution logs are written only when the process finishes. If the process is stopped abruptly, logs are missing and the run cannot be cleanly paused or resumed.
- **Where:** Logging / persistence layer (e.g. where `execution_logs.json` or equivalent is written).
- **Tasks:**
  - [x] Persist logs incrementally (e.g. append per node or per N events), not only at end.
  - [x] Ensure log file is flushed (or synced) after each append so a crash still leaves a usable log.
  - [ ] Define a "checkpoint" or "resume" model: e.g. last completed node + last written log position; document how resume would use them (future work).
  - [ ] Optionally: separate "live view" (e.g. WebSocket/stream) from "durable log" (file) so UI can show progress even when file is written asynchronously.

---

## 4. Workflow and environment

### 4.1 Manual phase loop limit ✅

- **What:** Manual/test phase stopped with "Loop limit reached (1)", ending the run after one manual iteration.
- **Where:** Loop counter or manual-phase config (e.g. in design YAML or runtime config).
- **Tasks:**
  - [x] Make manual-phase loop limit configurable (e.g. per design or per run).
  - [x] Consider higher default for "complex application" flows (or document when to increase it).

### 4.2 Python version mismatch (venv vs project) ✅

- **What:** Venv created with Python 3.10 while project specifies `requires-python: ==3.12.*`, causing version drift.
- **Where:** `init_python_env` / uv venv creation (e.g. in `functions/function_calling/uv_related.py`).
- **Tasks:**
  - [x] When creating venv, derive Python version from project (e.g. `pyproject.toml` or lockfile) when available.
  - [x] Fallback: use same interpreter as current process or a configurable default; document the choice.

### 4.3 UV hardlink warning ✅

- **What:** "Failed to hardlink files; falling back to full copy" in logs (cosmetic/performance).
- **Where:** UV invocation (e.g. install/run helpers).
- **Tasks:**
  - [x] Optional: set `UV_LINK_MODE=copy` in the environment where uv runs to suppress the warning when hardlinks aren't supported.

---

## Reference

- **Session:** `WareHouse/session_cd13c0a5-ea51-41c3-a26d-ed25646a1a3c`
- **Artifacts:** `execution_logs.json`, `workflow_summary.yaml`, `code_workspace/`
- **Design:** `yaml_instance/ChatDev_v1_PY.yaml`
