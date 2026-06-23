# Caelo — Backend API reference

The Caelo sidecar (`caelo-core`, FastAPI/uvicorn) exposes a local HTTP + WebSocket API consumed by
the Electron renderer. This document is the reference for that surface: **109 REST routes + 6
WebSocket endpoints** (count verified via the snippet in [Regenerating this list](#regenerating-this-list);
a few M20 chat-media routes are reflected in the count but not yet split into their own table).

> End users want **[USER_GUIDE.md](USER_GUIDE.md)**. This file is for developers and integrators.
> A machine-readable schema is also served at **`GET /openapi.json`** by the running sidecar.

---

## Connection, handshake & auth

- **Binding.** The sidecar binds **`127.0.0.1` only** (never a routable interface) on a free port.
- **Handshake.** On startup it prints exactly one line to stdout:
  `__CAELO_CORE_READY__ {"port":…,"token":…,"version":…}`. Electron parses it to learn the
  `baseUrl` (`http://127.0.0.1:<port>`) and session `token`. uvicorn logs go to stderr so stdout
  stays clean.
- **REST auth.** Every route **except `/health`** requires
  `Authorization: Bearer <token>` (constant-time compare). Missing → `401`, wrong → `403`.
- **WebSocket auth.** Browsers can't set headers on WS, so the token goes in the query:
  `ws://127.0.0.1:<port><path>?token=<token>`. WS also enforce an **Origin** check (loopback /
  `file://` / `null`).
- **Fail-closed.** With **no** configured token, both REST and WS **deny all** requests unless
  `CAELO_CORE_ALLOW_NO_TOKEN=1` is set (explicit dev opt-in; logged at startup and **per request**).
- **CORS.** Restricted to dev loopback + packaged `file://` (Origin `null`); no `*`, no credentials.
- **Errors.** Upstream (xAI) failures return a generic message; raw errors are logged server-side,
  not leaked to the client.

---

## Unauthenticated / handshake

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness probe (no token). Returns `{status, service, version}`. |
| `GET` | `/whoami` | Confirms a valid session token; returns version/port/`backend_ready`. |

## Auth (`/auth`)

| Method | Path | Description |
|---|---|---|
| `POST` | `/auth/login` | Begin / complete xAI OAuth (PKCE) login. |
| `POST` | `/auth/logout` | Clear stored OAuth tokens. |
| `GET` | `/auth/status` | Auth state (`has_api_key`, OAuth signed-in) — **never** returns the key. |

## Models & settings

| Method | Path | Description |
|---|---|---|
| `GET` | `/models` | List available chat models. |
| `GET` | `/settings` | Current settings (key is masked → `has_api_key` flag only). |
| `PUT` | `/settings` | Update settings (api key, chat/code model, system prompt, temperature, search/voice defaults). |
| `GET` | `/config/output-dir` | Current media output directory. |
| `PUT` | `/config/output-dir` | Change the media output directory. |

## Media — direct generation (legacy path)

Prefer the **GenJobs** queue below for new work; these are the direct/legacy calls.

| Method | Path | Description |
|---|---|---|
| `POST` | `/images/generate` | Text → image. |
| `POST` | `/images/edit` | Edit / variation from reference image(s). |
| `POST` | `/video/jobs` | Create a video job (text2video / img2video). |
| `GET` | `/video/jobs/{job_id}` | Poll a video job's status. |
| `POST` | `/video/edits` | Edit an existing video. |
| `POST` | `/video/extensions` | Extend an existing video. |

## Generation queue — GenJobs (M11)

Unified async queue for image & video (statuses: queued → running → done/failed/cancelled).

| Method | Path | Description |
|---|---|---|
| `GET` | `/genjobs` | List jobs (+ `total_cost`). |
| `DELETE` | `/genjobs` | Clear finished jobs. |
| `POST` | `/genjobs/image` | Enqueue an image job (text2img / edit / variation; ≤3 refs). |
| `POST` | `/genjobs/video` | Enqueue a video job (text2video / img2video / edit / extend). |
| `GET` | `/genjobs/{job_id}` | Get one job. |
| `DELETE` | `/genjobs/{job_id}` | Remove a finished job. |
| `POST` | `/genjobs/{job_id}/cancel` | Cancel a queued/running job. |
| `POST` | `/genjobs/{job_id}/retry` | Retry a failed job. |

## Voice (M12)

| Method | Path | Description |
|---|---|---|
| `POST` | `/voice/tts` | Text-to-speech (5 voices, language); returns audio + `chars`/`cost`. |
| `POST` | `/voice/stt` | Batch speech-to-text; `cost` derived from duration. |

WebSocket voice endpoints are in [WebSocket endpoints](#websocket-endpoints).

## Workspace files (`/fs`) — agent/IDE

All paths are sandboxed to the active workspace root.

| Method | Path | Description |
|---|---|---|
| `GET` | `/fs/workspace` | Current workspace root (or none). |
| `POST` | `/fs/workspace` | Select / set the workspace root. |
| `GET` | `/fs/recent` | Recent workspaces. |
| `GET` | `/fs/tree` | Directory tree of the workspace. |
| `GET` | `/fs/read` | Read a file (sandboxed). |
| `POST` | `/fs/write` | Write a file (sandboxed, atomic). |

## Git (`/git`)

| Method | Path | Description |
|---|---|---|
| `GET` | `/git/status` | Working-tree status. |
| `GET` | `/git/diff` | Diff. |
| `POST` | `/git/add` | Stage files. |
| `POST` | `/git/commit` | Commit. |

## Hub history & artifacts (M9)

| Method | Path | Description |
|---|---|---|
| `GET` | `/history` | Search hub events (FTS), filterable by project. |
| `GET` | `/history/generations` | Generation history. |
| `GET` | `/artifacts` | List artifacts (images/video/audio…). |
| `GET` | `/artifacts/{artifact_id}` | Artifact metadata. |
| `GET` | `/artifacts/{artifact_id}/content` | Artifact file content (sandboxed to media dirs). |
| `GET` | `/artifacts/{artifact_id}/input-block` | Artifact as a chat input block (for send-to). |
| `DELETE` | `/artifacts/{artifact_id}` | Delete record + file from disk. |

## Projects (M9-B5; M22: chat vs code)

M22 split projects via a `kind` discriminator (`'chat'` | `'code'`). `GET /projects` returns only
**chat** projects (Code workspaces are `kind='code'`, bound by `set_workspace` and not shown here);
chat projects carry per-project `instructions` (prepended to the chat system prompt).

| Method | Path | Description |
|---|---|---|
| `GET` | `/projects` | List **chat** projects (+ `recent_workspaces`, `current_project_id`). |
| `POST` | `/projects` | Create a chat project (or, for a `root`, a code project). |
| `POST` | `/projects/current` | Set the active chat project (`null` clears). |
| `PATCH` | `/projects/{id}` | Rename and/or set `instructions` (M22). |
| `DELETE` | `/projects/{id}` | Delete project + its history/artifacts/gen-jobs/knowledge (M22). |

## Project knowledge / collections (M10-B5)

Local documents attached to a project (xAI has no server-side vector stores). Scoped to the
**active** project; in the renderer these are managed inside the `ProjectSwitcher` (M22, the old
`KnowledgePopover` was absorbed).

| Method | Path | Description |
|---|---|---|
| `GET` | `/collections` | List the active project's knowledge documents. |
| `POST` | `/collections/files` | Upload a document to the active project. |
| `GET` | `/collections/files/{file_id}/content` | Serve a document (sandboxed to `PROJECT_DOCS_DIR`). |
| `DELETE` | `/collections/files/{file_id}` | Remove a document (record + file). |

## Agent — checkpoints, undo, CAELO.md (M13)

| Method | Path | Description |
|---|---|---|
| `GET` | `/agent/checkpoints` | List checkpoints for the active workspace. |
| `POST` | `/agent/undo` | Roll back to a checkpoint. |
| `GET` | `/agent/caelo-md` | Read the workspace `CAELO.md` (+ whether one exists). |
| `PUT` | `/agent/caelo-md` | Write the workspace `CAELO.md` (atomic, sandboxed). |

## Agent — sessions (M21)

Saved, resumable coding sessions (`DATA_DIR/sessions/<id>.json`; the store is shared with headless
mode). The WS `/agent/stream` persists the full session after each turn and can resume one via a
`session` frame.

| Method | Path | Description |
|---|---|---|
| `GET` | `/agent/sessions?project_id=` | List session metadata (newest first; filter by project). |
| `GET` | `/agent/sessions/{id}` | Full session (raw LLM history) for transcript + resume. |
| `DELETE` | `/agent/sessions/{id}` | Delete a saved session. |

## Agent — permission allowlist

| Method | Path | Description |
|---|---|---|
| `GET` | `/permissions` | The "Always allow" allowlist. |
| `DELETE` | `/permissions` | Clear the allowlist. |

## Agent teams — subagents (M17)

| Method | Path | Description |
|---|---|---|
| `GET` | `/agent/team/roles` | List roles (built-in + user overrides). |
| `POST` | `/agent/team/roles` | Create / override a role. |
| `DELETE` | `/agent/team/roles/{role_id}` | Delete a role override (built-in reverts to default). |
| `PUT` | `/agent/team/limits` | Set team limits (parallelism, budgets, timeouts). |
| `GET` | `/agent/team/merges` | Pending worktree merges (subagent changes). |
| `DELETE` | `/agent/team/merges` | Clear pending merges. |
| `GET` | `/agent/team/merges/{merge_id}/diff` | Unified diff for a pending merge. |
| `POST` | `/agent/team/merges/{merge_id}/apply` | Apply a merge (snapshots originals into a checkpoint). |
| `POST` | `/agent/team/merges/{merge_id}/reject` | Discard a merge. |
| `GET` | `/agent/team/runs` | Recent team-run reports (telemetry). |

## Extensibility — MCP servers (M14)

| Method | Path | Description |
|---|---|---|
| `GET` | `/mcp` | List configured MCP servers (secrets masked). |
| `POST` | `/mcp` | Add an MCP server config. |
| `GET` | `/mcp/{sid}` | Server detail (secrets masked). |
| `DELETE` | `/mcp/{sid}` | Remove a server. |
| `PUT` | `/mcp/{sid}/enabled` | Enable/disable a server. |
| `POST` | `/mcp/{sid}/start` | Start a stdio server (gated, hardened subprocess). |
| `POST` | `/mcp/{sid}/stop` | Stop a server (tree-kill). |

## Extensibility — commands, skills, hooks (M14)

| Method | Path | Description |
|---|---|---|
| `GET` | `/commands` | List slash commands (built-in + user). |
| `POST` | `/commands` | Add a user command (prompt template). |
| `DELETE` | `/commands/{name}` | Remove a user command. |
| `GET` | `/skills` | List skills. |
| `POST` | `/skills` | Add a skill. |
| `GET` | `/skills/{sid}` | Skill detail. |
| `PUT` | `/skills/{sid}/enabled` | Enable/disable a skill (enabled skills inject into the agent prompt). |
| `DELETE` | `/skills/{sid}` | Remove a skill. |
| `GET` | `/hooks` | List hooks. |
| `POST` | `/hooks` | Add a hook. |
| `PUT` | `/hooks/{hid}/enabled` | Enable/disable a hook. |
| `DELETE` | `/hooks/{hid}` | Remove a hook. |
| `GET` | `/hooks/audit` | Read the tool-call audit log. |
| `DELETE` | `/hooks/audit` | Clear the audit log. |

## Marketplace — packages (M16)

| Method | Path | Description |
|---|---|---|
| `GET` | `/packages` | List installed packages. |
| `POST` | `/packages/inspect` | Inspect a `.caelopkg` (consent card; installs **nothing**). |
| `POST` | `/packages/install` | Install (requires explicit consent + integrity match). |
| `POST` | `/packages/export` | Export a skill/command/MCP/template as `.caelopkg` (secrets stripped). |
| `GET` | `/packages/registry` | Fetch a git/GitHub registry index. |
| `GET` | `/packages/updates` | Check installed packages for updates. |
| `GET` | `/packages/templates` | List project templates (built-in + user). |
| `POST` | `/packages/templates/{tid}/new-project` | Instantiate a template into a folder → new project. |
| `DELETE` | `/packages/{pid}` | Uninstall a package. |

---

## WebSocket endpoints

All take the token in the query (`?token=…`) and enforce the Origin check. Blocking xAI work runs
in a worker thread; deltas/events are pushed over a bounded queue with backpressure (`WsStream`).
A `{"type":"stop"}` frame from the client cancels the in-flight operation.

| Path | Purpose | Notable frames (server → client) |
|---|---|---|
| `/chat/stream` | Chat over the Responses API (search, vision, tools). | `delta` · `tool_call` · `citations` · `usage` · `done` · `error` |
| `/agent/stream` | Coding-agent session loop (tools + approvals). | `delta`/event · `approval_request` · `workspace` · `session` (M21: active session id; client may send `{"type":"session","id":…\|null}` to resume/start) · `subagent`/`subagent_status` · `team_done` · `error` |
| `/terminal` | Embedded pty shell (needs `pywinpty`). | pty output frames |
| `/voice/converse` | **Talk** mode: transcript → Responses → TTS, with barge-in. | `audio` (+ text) frames; `{"type":"stop"}` = barge-in |
| `/voice/realtime` | **Live** mode: transparent proxy to xAI Voice Agent (`/v1/realtime`). | raw passthrough frames |
| `/voice/stt/stream` | Live streaming STT (partials + final). | partial/final transcript frames |

The exact WS frame protocols are documented in the docstrings atop
[`routes/chat.py`](../../caelo_core/routes/chat.py) and [`routes/agent.py`](../../caelo_core/routes/agent.py).

---

## Regenerating this list

The route inventory above is authoritative as of the current build. To regenerate the complete,
deduplicated list (e.g. after adding routes), introspect the app:

```python
from caelo_core.server import create_app
from fastapi.routing import APIRoute, APIWebSocketRoute
app = create_app(token="x", port=0)
for r in app.routes:
    if isinstance(r, APIRoute):
        print(",".join(sorted(r.methods - {"HEAD", "OPTIONS"})), r.path)
    elif isinstance(r, APIWebSocketRoute):
        print("WS", r.path)
```

Or fetch the OpenAPI schema from a running sidecar: `GET /openapi.json` (WS endpoints are not in
OpenAPI — they're listed above).
