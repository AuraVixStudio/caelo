# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Desktop app for **Grok (xAI)** in the style of Claude Code / Codex: chat, image/video
generation & editing, and an **agentic coding module** with local file access. It is a
**monorepo rebuild** of an older customtkinter (Python) app into **Electron (frontend) +
Python FastAPI sidecar (backend)**. The mature xAI logic (OAuth, SSE streaming, media) is
**reused, not rewritten**. Full plan & phase status live in [`docs/REBUILD_PLAN.md`](docs/REBUILD_PLAN.md)
(source of truth). The old customtkinter app has been **removed from the repo** (kept as an external
backup) — Phase 8 closed.

## The single most important structural fact

The shared xAI core lives at the **repo root**, NOT inside `grok_core/`:
`config.py`, `api_manager.py`, `oauth_manager.py`, `chats_manager.py`, `history_manager.py`,
and `make_icon.py`. The `grok_core` sidecar imports these as top-level modules (`import config`,
`from api_manager import APIManager`, …) — `grok_core/__init__.py` prepends the repo root to
`sys.path` at import time so this works, and `grok_core.spec` declares them as `hiddenimports`
with `pathex='.'`. (The now-removed `archive/app.py` also reused them via a `sys.path` shim — hence
they predate the sidecar — but the binding constraint is the sidecar + PyInstaller + data paths.)

**Do not move, rename, or restructure these root modules.** Doing so breaks `grok_core` imports,
the PyInstaller build, and (via `config.py`) every data-file path. New backend code belongs in
`grok_core/`; only touch the root modules to fix shared xAI logic.

## Architecture

```
Electron main (desktop/src/main/index.ts)
  • spawns the sidecar (dev: `python -m grok_core`; packaged: resources/grok-core/grok-core.exe)
  • generates a session token → GROK_CORE_TOKEN env; reads handshake line from sidecar stdout
  • /health monitor every 10s, auto-restart on crash (≤5 tries); kills sidecar on quit
        │  preload (contextBridge) exposes window.grok  →  Renderer (React 19 + TS)
        ▼  HTTP REST + WebSocket — 127.0.0.1 only, bearer/query token
Python sidecar "grok-core" (FastAPI/uvicorn, grok_core/)
  • server.py mounts routers; state.py Backend wraps reused legacy managers + keys/settings
  • agent/ = coding-agent engine (workspace sandbox, permission gate, tools, llm, session loop)
        │  Bearer token (OAuth access token → API key → XAI_API_KEY) — only to api.x.ai
        ▼  xAI / Grok API
```

**Handshake:** the sidecar binds a free port on `127.0.0.1` and prints exactly one line to
stdout: `__GROK_CORE_READY__ {"port":…,"token":…,"version":…}`. uvicorn logs go to stderr so
stdout stays clean. Electron parses this; the token it generated (passed via `GROK_CORE_TOKEN`)
is authoritative. See [`grok_core/__main__.py`](grok_core/__main__.py) and `index.ts`.

**Auth precedence** (`Backend.get_api_key` in [`grok_core/state.py`](grok_core/state.py)):
OAuth access token → saved `api_key` from settings → `XAI_API_KEY` from `.env`. OAuth uses the
public PKCE `client_id` of grok-cli/Hermes and undocumented `auth.x.ai` endpoints (see
[`config.py`](config.py)) — may break server-side without notice.

**Coding agent** ([`grok_core/agent/`](grok_core/agent/)): an event-driven LLM loop
(`session.py`) with file tools (`tools.py`: read_file/list_dir/glob/grep/write_file/edit_file/
run_command). READONLY tools run freely; MUTATING tools (write/edit/run) go through
`PermissionGate` (`permissions.py`) and require user approval unless "Always allow"-listed.
All file paths are sandboxed to the workspace root via `Workspace.resolve` (`workspace.py`,
rejects `..`/absolute escapes); `run_command` is NOT sandboxed in command content, hence approval.
The approval allowlist is persisted to `grok_permissions.json` and shared by the agent WS and the
REST `/permissions` routes.

**Agent hardening (M1, see [`docs/PLAN_NAPRAWY.md`](docs/PLAN_NAPRAWY.md) P0-1…P0-8 — all done):**
`run_command` **rejects shell metacharacters** (`command_metachars` in `permissions.py`) so the
"Always allow" allowlist can't be bypassed by chaining (`git && rm`); the allowlist key is the full
normalized command, not the exe name. It runs with a **scrubbed env** (no `GROK_CORE_TOKEN`/
`XAI_API_KEY`/secret-like vars), **tree-kills** on Stop/timeout (Windows `taskkill /T /F`), and Stop
propagates from the session. `glob`/`grep`/`list_dir` are sandboxed (reject escapes incl.
symlinks/**junctions** via `resolve()`); `grep` has a ReDoS wall-clock timeout (`regex` module) +
size/binary skips. Interrupted `tool_calls` get synthetic `tool` results so history stays balanced
(xAI contract). Writes are atomic (`tools.atomic_write_text`). Don't regress these — `agent_selfcheck.py`
asserts them (81 checks).

**Round-2 hardening (M5–M6, see [`docs/PLAN_NAPRAWY_2.md`](docs/PLAN_NAPRAWY_2.md) — done):** the
agent WS now uses the shared **`WsStream`** (bounded queue + worker join on disconnect, so the agent
can't write files / run commands after the socket is gone — P0-9); `command_metachars` is
**POSIX-aware** and `run_command` runs `shell=False`+`shlex` off-Windows (P0-10); the **terminal pty
env is scrubbed** like `run_command` (P0-11); REST `require_token` is **fail-closed** like WS (P1-10);
all five JSON readers go through `config.load_json_or_backup` (corrupt → `.corrupt` backup) and
`grok_permissions.json`/`grok_auth.json` writes are atomic (P1-11); agent approval has a timeout (P1-12);
`auth.py`/`git.py` no longer leak raw errors (P1-13); media downloads are https-only + size-capped (P1-14).

**Streaming bridge:** blocking xAI calls run in a worker thread; deltas/events go through the shared
**`WsStream`** ([`routes/_ws.py`](grok_core/routes/_ws.py)) — a bounded asyncio queue + sender task +
threadsafe `emit()` (backpressure) + `send()` (event-loop) + worker `track()`/join — used by
`/chat/stream`, `/agent/stream` and `/terminal` (one skeleton, so fixes can't drift between routes).
A `{"type":"stop"}` frame sets a `threading.Event`. See the WS protocol docstrings at the top of
[`routes/chat.py`](grok_core/routes/chat.py) and [`routes/agent.py`](grok_core/routes/agent.py).

## Commands

All paths below are relative to the repo root. The frontend npm scripts run from `desktop/`.

**Dev (run the app):**
```powershell
# one-time backend venv (in network with TLS interception add: --trusted-host pypi.org --trusted-host files.pythonhosted.org)
cd grok_core; python -m venv .venv; .venv\Scripts\pip install -r requirements.txt; cd ..
# NOTE: requirements now includes `regex` (P0-3 ReDoS-safe grep). Re-run the pip line above if you have an existing venv.
cd desktop; npm install         # one-time
npm run dev                     # Electron + Vite HMR; main process spawns the sidecar
```
Electron finds Python in this order: `GROK_CORE_PYTHON` env → `grok_core/.venv/Scripts/python.exe`
→ system `python`. Override: `$env:GROK_CORE_PYTHON = "C:\path\python.exe"; npm run dev`.

**Type-check the frontend (primary check) + ESLint + Vitest:**
```powershell
cd desktop; npm run typecheck   # tsc for both node (main/preload) and web (renderer)
# One-time activation of lint/test (M8 was authored offline, so the devDeps are NOT in package.json —
# adding them there without updating package-lock.json would break CI's `npm ci`). Install them:
npm install -D eslint typescript-eslint eslint-plugin-react-hooks globals vitest
npm run lint                    # P3-7: ESLint flat config (eslint.config.mjs), react-hooks rules only
npm test                        # P3-9: Vitest unit tests for pure renderer utils (desktop/test/)
```
ESLint is **deliberately narrow** — only `react-hooks` rules (the real gap), not the full recommended
sets. Vitest tests live in `desktop/test/` (outside the tsconfig include, so they don't affect
`typecheck`). The configs + tests are committed and ready; only the `npm install -D` above is pending
(it updates `package.json` + `package-lock.json` together, keeping `npm ci` happy).

**Backend self-checks (this repo's "tests" — no pytest; each script is a self-contained suite):**
```powershell
grok_core\.venv\Scripts\python grok_core\tools\handshake_check.py   # handshake + /health + token auth
grok_core\.venv\Scripts\python grok_core\tools\api_smoke.py         # REST + WS routes + token enforcement
grok_core\.venv\Scripts\python grok_core\tools\agent_selfcheck.py   # agent tools + loop (mocked LLM)
grok_core\.venv\Scripts\python grok_core\tools\sidecar_smoke.py     # packaged-sidecar smoke (after pack:sidecar)
```
To run a single suite, run just that one script. They use mocks where xAI is needed.

**Run the backend standalone (from the repo root, not from `grok_core/`):**
```powershell
grok_core\.venv\Scripts\python -m grok_core
```

**Packaging (.exe installer — Windows):**
```powershell
cd desktop
npm run pack:sidecar   # PyInstaller onedir → ../dist/grok-core/grok-core.exe (from grok_core/.venv)
npm run dist           # frontend build + electron-builder NSIS → desktop/dist/Grok-Desktop-Setup-*.exe
npm run dist:full      # all of the above in one shot
```
`dist`/`dist:full` download NSIS + Electron binaries from the network, so run them on the user's
machine. Packaged sidecar runs with `sys.frozen=True`, which moves `config.DATA_DIR` to
`%LOCALAPPDATA%\AI Studio Pro`.

The legacy customtkinter app has been removed from the repo (kept as an external backup); there is no
longer a `cd archive; python app.py` fallback here.

## Data files (ownership rules — easy to corrupt)

All resolved in [`config.py`](config.py). Dev: alongside the repo. Packaged (`IS_FROZEN`):
`%LOCALAPPDATA%\AI Studio Pro`. (Historically these were shared with the legacy app; a separately
run external copy would use its own `config.py`, hence its own data dir.)

- `grok_config.json` — **owned exclusively by `HistoryManager`**, rewritten wholesale (history /
  chat_history / save_path only). Never write anything else here — it wipes the data.
- `grok_settings.json` — API key (fallback), chat/code model, system prompt, temperature, `recent_workspaces`.
- `grok_auth.json` — OAuth tokens (gitignored; never commit).
- `grok_chats.json` — legacy conversation store. **No longer written by the sidecar** (P2-8: `ChatStore`
  removed from `Backend`); chat conversations now live in the renderer's `localStorage` (`useConversations`).
  `chats_manager.py` stays in the root (reusable) but is not instantiated.
- `grok_permissions.json` — agent "Always allow" allowlist (atomic writes, P1-11).

All five JSON readers go through **`config.load_json_or_backup`** (P1-11): a corrupt file is moved to
`<name>.corrupt` and logged, not silently wiped. The API key is **stored but never returned** by
`/settings` (only `has_api_key`).

## Project conventions (override defaults)

- **All user-facing UI text MUST be in English** — every `text=`, title, dialog, button, media
  caption, tool/OAuth string. Code comments and docstrings may stay in Polish (much of the existing
  code is). Note: regexes that match *user input* (not displayed text) may legitimately contain Polish
  patterns — that's not a UI-language violation.
- **SSE/streaming must be decoded as explicit UTF-8.** `requests` guesses ISO-8859-1 for
  `text/event-stream`, which mangles non-ASCII (e.g. Polish) characters. The reused
  `api_manager.chat_completion_stream` uses `iter_lines(decode_unicode=False)` + `.decode("utf-8")`
  and sets `r.encoding = "utf-8"` for non-streaming. Preserve this.
- **Editor is CodeMirror 6, deliberately not Monaco** (Monaco is too heavy under Vite/Electron).
  Isolated in `desktop/src/renderer/src/components/code/CodeEditor.tsx`.
- **Renderer styling is Tailwind v4 (CSS-first) — the old monolithic `styles.css` is gone.** Design
  tokens + light/dark themes live in `src/renderer/src/index.css` (`:root`/`.dark` vars mapped via
  `@theme inline`; `@custom-variant dark` = `.dark` class on `<html>`). Theme state in
  `src/renderer/src/lib/theme.tsx` (`useTheme`, light/dark/system). Reusable primitives in
  `src/renderer/src/components/ui/`. Build new UI with these — don't recreate per-component CSS.
- **Resizable panels use `react-resizable-panels` v4**: `Group`/`Panel`/`Separator` + `useDefaultLayout({id})`
  (NOT classic `PanelGroup`/`PanelResizeHandle`/`autoSaveId`). Sizes are `%` strings (bare numbers = px).
  Wrapper: `components/ui/ResizeHandle.tsx`. The left rail is a collapse-toggle sidebar, not a drag panel.
- **Browser UI preview without Electron:** `cd desktop; npm run preview:web` (Vite on :4599) — `main.tsx`
  installs a `window.grok` stub from `lib/devMock.ts` under `import.meta.env.DEV && !window.grok`
  (stripped from production), so you can eyeball the redesign without spawning the sidecar.
- The backend binds **127.0.0.1 only**; never expose it on a routable interface. REST uses
  `Authorization: Bearer <token>` (constant-time compare); WebSockets take the token in the query
  (`?token=`) because browser WS cannot set headers. **Both REST and WS are fail-closed** (WS: P0-8;
  REST `require_token`: P1-10): `state.ws_authorized` requires the token + an allowed `Origin`
  (loopback / `file://` / `null`), and with NO configured token **both deny** unless
  `GROK_CORE_ALLOW_NO_TOKEN=1` is set (explicit dev opt-in; `server.py` logs a warning on startup).
  CORS is narrowed to dev loopback + packaged `file://` (P1-9), not `*`. The renderer ships a
  **CSP** meta (P2-10: source-restricted `connect-src`/`img-src`/…), and `main/index.ts` blocks
  off-origin navigation (`will-navigate`) and allows only `media` permission requests (mic).
- **Shared backend helpers** (reuse them, don't reinvent). M1/M2: `grok_core/errors.py`
  `upstream_error()` (log raw exc → return generic detail; use for xAI 5xx / `auth.py` so raw errors
  don't leak), `grok_core/validation.py` (route input limits + data-URI validators, used in
  `media.py`/`voice.py` Pydantic models), `config.atomic_write_text()` (temp + `os.replace` for all
  JSON state writes). M5–M6: `routes/_ws.py` **`WsStream`** (the WS streaming skeleton — see above),
  `state.require_workspace` (FastAPI dep used by `/fs` + `/git`; was the duplicated `_require_ws`),
  `tools.scrubbed_env()` (secret-free env for `run_command` **and** the terminal pty),
  `config.load_json_or_backup()` (corrupt-tolerant JSON load for all five state files).
  Server logs go to **stderr** (`logging`, configured in `__main__.py`) — never `print()` to stdout
  (reserved for the handshake line).

## Verification limits

- **Real xAI calls** (chat content, image/video, OAuth login, full agent runs) need valid
  credentials + network and are verified on the **user's machine** — a TLS-intercepting sandbox
  blocks `api.x.ai`. The self-checks above mock xAI.
- The **Terminal** module needs `pip install pywinpty` in the backend venv (the agent's
  `run_command` tool works without it).
