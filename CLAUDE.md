# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Desktop app for **Grok (xAI)** in the style of Claude Code / Codex: chat, image/video
generation & editing, and an **agentic coding module** with local file access. It is a
**monorepo rebuild** of an older customtkinter (Python) app into **Electron (frontend) +
Python FastAPI sidecar (backend)**. The mature xAI logic (OAuth, SSE streaming, media) is
**reused, not rewritten**. Full plan & phase status live in [`docs/plans/REBUILD_PLAN.md`](docs/plans/REBUILD_PLAN.md)
(source of truth). The old customtkinter app has been **removed from the repo** (kept as an external
backup) — Phase 8 closed.

## The single most important structural fact

The shared xAI core lives at the **repo root**, NOT inside `caelo_core/`:
`config.py`, `api_manager.py`, `oauth_manager.py`, `chats_manager.py`, `history_manager.py`,
and `make_icon.py`. The `caelo_core` sidecar imports these as top-level modules (`import config`,
`from api_manager import APIManager`, …) — `caelo_core/__init__.py` prepends the repo root to
`sys.path` at import time so this works, and `caelo_core.spec` declares them as `hiddenimports`
with `pathex='.'`. (The now-removed `archive/app.py` also reused them via a `sys.path` shim — hence
they predate the sidecar — but the binding constraint is the sidecar + PyInstaller + data paths.)

**Do not move, rename, or restructure these root modules.** Doing so breaks `caelo_core` imports,
the PyInstaller build, and (via `config.py`) every data-file path. New backend code belongs in
`caelo_core/`; only touch the root modules to fix shared xAI logic.

## Architecture

```
Electron main (desktop/src/main/index.ts)
  • spawns the sidecar (dev: `python -m caelo_core`; packaged: resources/caelo-core/caelo-core.exe)
  • generates a session token → CAELO_CORE_TOKEN env; reads handshake line from sidecar stdout
  • /health monitor every 10s, auto-restart on crash (≤5 tries); kills sidecar on quit
        │  preload (contextBridge) exposes window.caelo  →  Renderer (React 19 + TS)
        ▼  HTTP REST + WebSocket — 127.0.0.1 only, bearer/query token
Python sidecar "caelo-core" (FastAPI/uvicorn, caelo_core/)
  • server.py mounts routers; state.py Backend wraps reused legacy managers + keys/settings
  • agent/ = coding-agent engine (workspace sandbox, permission gate, tools, llm, session loop)
        │  Bearer token (OAuth access token → API key → XAI_API_KEY) — only to api.x.ai
        ▼  xAI / Grok API
```

**Handshake:** the sidecar binds a free port on `127.0.0.1` and prints exactly one line to
stdout: `__CAELO_CORE_READY__ {"port":…,"token":…,"version":…}`. uvicorn logs go to stderr so
stdout stays clean. Electron parses this; the token it generated (passed via `CAELO_CORE_TOKEN`)
is authoritative. See [`caelo_core/__main__.py`](caelo_core/__main__.py) and `index.ts`.

**Auth precedence** (`Backend.get_api_key`/`_resolve_auth` in [`caelo_core/state.py`](caelo_core/state.py)):
the default (`auth_source="auto"`) is OAuth access token → saved `api_key` from settings → `XAI_API_KEY`
from `.env`. A **hard source switch** (`auth_source` in `caelo_settings.json`, set via Settings →
"Model source": auto/oauth/api_key) overrides this: `oauth` uses **only** the account token, `api_key`
uses **only** a key (settings → `.env`) — neither silently falls back to the other, so picking "API key"
with no key fails clearly instead of quietly using OAuth (the live A3 gap). `active_auth_source()` reports
the source actually in effect (`oauth|api_key|env|none`) — surfaced in `/auth/status` (+`has_stored_key`/
`has_env_key`); the renderer footer shows "Not signed in" when the sidecar is up but no source is active,
and the API-key field is removable (`DELETE /settings/api-key`) and masked (dots) when stored. OAuth uses the
public PKCE `client_id` of grok-cli/Hermes and undocumented `auth.x.ai` endpoints (see
[`config.py`](config.py)) — may break server-side without notice.

**Coding agent** ([`caelo_core/agent/`](caelo_core/agent/)): an event-driven LLM loop
(`session.py`) with file tools (`tools.py`: read_file/list_dir/glob/grep/write_file/edit_file/
run_command). READONLY tools run freely; MUTATING tools (write/edit/run) go through
`PermissionGate` (`permissions.py`) and require user approval unless "Always allow"-listed.
All file paths are sandboxed to the workspace root via `Workspace.resolve` (`workspace.py`,
rejects `..`/absolute escapes); `run_command` is NOT sandboxed in command content, hence approval.
The approval allowlist is persisted to `caelo_permissions.json` and shared by the agent WS and the
REST `/permissions` routes.

**Agent hardening (M1, see [`docs/plans/zrealizowane/PLAN_NAPRAWY.md`](docs/plans/zrealizowane/PLAN_NAPRAWY.md) P0-1…P0-8 — all done):**
`run_command` **rejects shell metacharacters** (`command_metachars` in `permissions.py`) so the
"Always allow" allowlist can't be bypassed by chaining (`git && rm`); the allowlist key is the full
normalized command, not the exe name. It runs with a **scrubbed env** (no `CAELO_CORE_TOKEN`/
`XAI_API_KEY`/secret-like vars), **tree-kills** on Stop/timeout (Windows `taskkill /T /F`), and Stop
propagates from the session. `glob`/`grep`/`list_dir` are sandboxed (reject escapes incl.
symlinks/**junctions** via `resolve()`); `grep` has a ReDoS wall-clock timeout (`regex` module) +
size/binary skips. Interrupted `tool_calls` get synthetic `tool` results so history stays balanced
(xAI contract). Writes are atomic (`tools.atomic_write_text`). A **loop guard** (`session.LOOP_GUARD_LIMIT`,
LIVE-verified) ends the turn cleanly when an IDENTICAL tool call (name+args) repeats past the limit within a
turn — models sometimes ignore "never loop on a failing edit" and re-issue the same `edit_file` until the file
is corrupted; the guard emits `info`+`stopped` with balanced history instead of executing it. Don't regress
these — `agent_selfcheck.py` asserts them (now 190+ checks, incl. `test_loop_guard`).

**Round-2 hardening (M5–M6, see [`docs/plans/zrealizowane/PLAN_NAPRAWY_2.md`](docs/plans/zrealizowane/PLAN_NAPRAWY_2.md) — done):** the
agent WS now uses the shared **`WsStream`** (bounded queue + worker join on disconnect, so the agent
can't write files / run commands after the socket is gone — P0-9); `command_metachars` is
**POSIX-aware** and `run_command` runs `shell=False`+`shlex` off-Windows (P0-10); the **terminal pty
env is scrubbed** like `run_command` (P0-11); REST `require_token` is **fail-closed** like WS (P1-10);
all five JSON readers go through `config.load_json_or_backup` (corrupt → `.corrupt` backup) and
`caelo_permissions.json`/`caelo_auth.json` writes are atomic (P1-11); agent approval has a timeout (P1-12);
`auth.py`/`git.py` no longer leak raw errors (P1-13); media downloads are https-only + size-capped (P1-14).

**Streaming bridge:** blocking xAI calls run in a worker thread; deltas/events go through the shared
**`WsStream`** ([`routes/_ws.py`](caelo_core/routes/_ws.py)) — a bounded asyncio queue + sender task +
threadsafe `emit()` (backpressure) + `send()` (event-loop) + worker `track()`/join — used by
`/chat/stream`, `/agent/stream` and `/terminal` (one skeleton, so fixes can't drift between routes).
A `{"type":"stop"}` frame sets a `threading.Event`. See the WS protocol docstrings at the top of
[`routes/chat.py`](caelo_core/routes/chat.py) and [`routes/agent.py`](caelo_core/routes/agent.py).

**Chat core = Responses API (M10, see [`docs/plans/zrealizowane/PLAN_M10_CZAT.md`](docs/plans/zrealizowane/PLAN_M10_CZAT.md)):** `/chat/stream`
runs through **[`caelo_core/responses_client.py`](caelo_core/responses_client.py)** (`POST /v1/responses`,
streaming) — live web/X search (`web_search`/`x_search`), vision (grok-4 family), document Q&A
(`input_file`), citations + token/usage counter. Legacy `chat_completion_stream` stays only as a
fallback for plain (no-tool) chat. New WS frames: `tool_call` · `citations` · `usage`; new `chat` fields:
`search_mode` (auto/on/off) + `sources`. **Don't restructure root `api_manager.py`** — the new client
is the thin endpoint/auth layer (CLAUDE.md rule). **Verified on the real API:** live search, vision,
`input_file` work; **xAI has NO server-side vector stores** (`/v1/vector_stores` → 404), so "project
knowledge" (B5) is **local** (`config.PROJECT_DOCS_DIR`) + attached on demand ("Attach all"), not
`file_search`. Mirror the `responses_client` UTF-8 SSE decode if you touch streaming.

**Creative = GenJob queue (M11, see [`docs/plans/zrealizowane/PLAN_M11_TWORCZOSC.md`](docs/plans/zrealizowane/PLAN_M11_TWORCZOSC.md)):** image
and video generation share **one async job engine** — [`caelo_core/genjobs.py`](caelo_core/genjobs.py)
`GenJobManager` (a `queue.Queue` + worker threads, statuses queued→running→done|failed|cancelled,
cancel/retry/`max_active` limit, cost estimate). The **executor is injected** by `Backend` — `genjobs.py`
must NOT import `api_manager`/`state` (no cycles, testable on a stub); `Backend._run_image_job`/
`_run_video_job` reuse the legacy `api_manager` calls + `save_media_urls` (the video worker polls
`poll_video_status` **server-side** so long renders don't block FastAPI). Every output is registered as an
**M9 Artifact**; `save_media_urls`/`_record_media_artifact` take `project_id` and return `artifact_id`.
Routes ([`routes/genjobs.py`](caelo_core/routes/genjobs.py)): `POST /genjobs/image` (text2img|edit|variation,
≤3 refs), `POST /genjobs/video` (text2video|img2video|edit|extend), `GET /genjobs`(+`total_cost`)/`{id}`,
`POST /{id}/cancel|retry`, `DELETE /genjobs[/{id}]` (clear finished). Media management: `DELETE
/artifacts/{id}` ([`routes/history.py`](caelo_core/routes/history.py)) removes the record + the file
(sandboxed to the media dirs). Transport is **REST polling** (`useGenJobs` polls `/genjobs` only while a
job is active); `GenJobManager.on_update` is an unused hook for an optional WS push. Selfcheck:
[`caelo_core/tools/genjobs_check.py`](caelo_core/tools/genjobs_check.py) (don't regress the lifecycle/cancel/
queue-limit asserts) + `/genjobs` guards in `api_smoke.py`. Renderer staged inputs (Image refs, Video
frame/source) live in the **Hub context** (`lib/hub.tsx`) — panels are lazy and unmount on tab switch,
so per-panel `useState` would lose them.

**Voice = bridges + conversation pipeline (M12, see [`docs/plans/zrealizowane/PLAN_M12_GLOS.md`](docs/plans/zrealizowane/PLAN_M12_GLOS.md)):**
all voice routes live in [`routes/voice.py`](caelo_core/routes/voice.py); audio flows
**renderer → sidecar → xAI** and the key NEVER reaches the renderer (the sidecar injects
`Authorization`). REST: `POST /voice/tts` (5 voices, language; returns audio + `chars`/`cost`) and
`POST /voice/stt` (batch; `cost` from `duration`). WS: `/voice/realtime` (B4 stretch — Voice Agent
`/v1/realtime`, the **Live** UI mode) and `/voice/stt/stream` (B1 — live STT) are **transparent
proxies** sharing `_bridge_upstream` (raw frame passthrough, UTF-8 — NOT `WsStream`, which is only
for blocking workers). The **conversation pipeline** `/voice/converse` (B3, the **Talk** UI mode)
IS on `WsStream`: it takes a final transcript → `responses_client.stream_response` (M10 tools +
M9 history) → `text_to_speech` → `audio` frame; single-flight, `{"type":"stop"}` = barge-in (skips
TTS), records the turn to M9. **Design choice:** the STT(stream) half is **client-side**
([`lib/converse.ts`](desktop/src/renderer/src/lib/converse.ts) drives `/voice/stt/stream` for
partials + final, then hands the transcript to `/voice/converse`) so one route never juggles two
upstream sockets. Renderer audio capture is the shared `MicCapture`
([`lib/audioStream.ts`](desktop/src/renderer/src/lib/audioStream.ts), PCM16 worklet) used by both
`realtime.ts` and `converse.ts`. Cost (B5): `stt_cost`/`tts_cost` (rates in `config.py`; TTS
per-char is a **tunable estimate**) → response fields + M9 meta; renderer accumulates per session
([`lib/audioCost.ts`](desktop/src/renderer/src/lib/audioCost.ts)). There is **no `/usage` route**
(like M11). Voice defaults (`voice`/`voice_language`) live in `caelo_settings.json`. Dictation
(`useDictation` in chat + agent) uses **batch** STT; live partials are the **Talk** mode. Selfcheck:
`api_smoke.py` `_unit_voice_converse` (pipeline + barge-in + cost) + WS bad-token rejection for the
new routes. **xAI streaming-STT protocol/sample-rate is unconfirmed** — `parseStt` handles variants
defensively; verify live.

**Extensibility = MCP + commands + hooks + skills (M14, see [`docs/plans/zrealizowane/PLAN_M14_ROZSZERZALNOSC.md`](docs/plans/zrealizowane/PLAN_M14_ROZSZERZALNOSC.md)):**
the hub became a **programmable platform** — tools serve chat AND the agent. The **MCP client** is a
**custom thin SYNCHRONOUS layer** (`caelo_core/mcp/`), NOT the official SDK (deliberate hybrid, like
`responses_client` vs the OpenAI SDK — zero new deps, fits the worker-thread model; `client.py` does
stdio newline-delimited JSON-RPC 2.0, transport is abstract (`McpTransport`) so HTTP/native-remote can
adopt the SDK later). Server subprocesses are hardened like `run_command` (**`tools.scrubbed_env()`** +
**`_tree_kill`**; Windows wraps `.cmd`/`npx` in `cmd /c`); starting a stdio server is an explicit,
gated user action. `McpManager` namespaces tools (`mcp__<server>__<tool>`), routes calls, classifies
gating by `annotations.readOnlyHint` (READONLY → no gate; else → `PermissionGate`, key `mcp:<name>`),
and masks secrets (`authorization`/`env` never returned to the renderer). **Agent**: `session.py`
merges MCP tool defs into `TOOLS`; mutating MCP calls go through the gate + approval card
(`detail.kind="mcp_tool_call"`). **Chat**: `responses_client.stream_response` gained a **client-side
function-call loop** (stream → `function_call` → `tool_handler` → `function_call_output` → next turn,
to `max_tool_iters`; FLAT Responses tool format) — chat has NO interactive approval, so mutating MCP
tools run only if pre-approved on the shared allowlist, else refused with a message. **Native remote
MCP (B3)**: `tools=[{type:'mcp',server_url,…}]` passed through to xAI (`remote_tools=`), xAI-side
execution, no local gate. **Hooks** (`caelo_core/hooks.py`, generalized `PermissionGate`):
`pre_tool`/`post_tool`/`pre_session`, deterministic, run in `session.py` BEFORE the gate; built-in
`block-dangerous-commands` (intent regex above P0-1) + `audit-all` (JSONL `caelo_audit.log`); user
`run_script` hooks (opt-in; auto-format after write). **Commands** (`caelo_core/commands/`): prompt
templates + optional `mode`/`action`, built-ins `/plan /review /commit /test /mcp` + user; surfaced in
the chat composer (`/`) and Ctrl-K palette (`lib/slashCommands.ts`, `lib/hub.tsx`). **Skills**
(`caelo_core/skills/`): `<id>/SKILL.md` packages (bundled `builtin/` general coding skills —
commit/write-tests/refactor/debug/document-code/explain-codebase + the M19 multi-agent orchestrators
implement/review/design/best-of-n/check-work/pr-babysit — via spec `collect_data_files`, + user
`SKILLS_DIR`); enabled skills inject into the agent system prompt (like
CAELO.md). New state files (all via `load_json_or_backup` + atomic writes, gitignored): `caelo_mcp.json`,
`caelo_commands.json`, `caelo_hooks.json`, `caelo_audit.log`, `skills/`. REST: `routes/mcp.py`,
`routes/hooks.py`, `routes/commands.py`, `routes/skills.py`; lazy `backend.mcp`/`.hooks`/`.commands`/
`.skills`; `backend.shutdown()` tree-kills MCP subprocesses in the server lifespan. Renderer module
**Extensions** (4 tabs). Selfchecks: `caelo_core/tools/mcp_check.py` (24, mock stdio server),
`agent_selfcheck.py` (MCP-in-agent + hooks → 139), `api_smoke.py` (`_unit_responses_mcp_loop`,
`_unit_mcp_routes`, `_unit_commands_skills`). **Real MCP servers / live chat verified on the user's
machine** (sandbox blocks them); don't regress P0-1…P0-8 / M5–M6.

**Agent teams = subagents (M17, see [`docs/plans/zrealizowane/PLAN_M17_SUBAGENCI.md`](docs/plans/zrealizowane/PLAN_M17_SUBAGENCI.md)):** the
orchestrator (top-level `AgentSession`) gets a **`delegate`** tool that fans out subtasks to specialized
**subagents**, each an **isolated sub-session on the same `session.py`** with its own history, a **role**
persona, a **narrowed tool set**, and (for mutating roles) an **isolated worktree** — the parent's
context stays clean (one `tool` message = the returned summaries, NOT the subagent transcript). Roles
([`agent/roles.py`](caelo_core/agent/roles.py) `RoleRegistry`, `caelo_subagents.json`): researcher/reviewer
= READONLY (no worktree); implementer/tester = mutating-in-worktree; `effective_tools` = role ∩ parent
(**no escalation**); subagents get **no `delegate`** → **depth = 1** (anti fork-bomb). `session.py` gained
optional `tool_names`/`delegate_fn`/`extra_system`/`on_turn` (additive, no regression). The team engine
([`agent/team.py`](caelo_core/agent/team.py) `TeamManager`) runs subagents concurrently (semaphore =
`max_parallel`, per-subagent timeout monitor), enforces **hard limits** (`roles.DEFAULT_LIMITS`:
parallel/subagents/turn-budget/timeout/iters; depth fixed 1) and **cascade stop** (orchestrator stop is
live in each subagent's stop closure → loops halt + `run_command` tree-kills). Worktree =
**copy of the workspace** ([`agent/worktree.py`](caelo_core/agent/worktree.py), like the M13 checkpoint —
no git, skips IGNORE_DIRS/symlinks); mutating roles auto-apply edits in their copy (review at merge, not
per-edit) and run in plan mode are skipped. **Merge review (B4):** changes surface as **one diff** +
conflict detection (same path in >1 worktree) via `MergeStore` (per workspace, shared WS↔REST like
checkpoints); apply snapshots originals into the **M13 checkpoint** (undoable) then writes (sandboxed),
reject discards the copy. MCP is scoped per role (`ScopedMcp`: readonly roles see only readonly tools).
Telemetry (B6): per-subagent turns/tool-calls/tokens (from streamed `usage` in [`agent/llm.py`](caelo_core/agent/llm.py),
popped before history so it never returns to xAI) + a recent-runs ring buffer. **Transport:** one
`WsStream` multiplexed by `agent_id` (frames `subagent`/`subagent_status`/`team_done`; subagent
`approval_request` carries `agent_id`/`role`/`task` for attribution). REST: [`routes/team.py`](caelo_core/routes/team.py)
`/agent/team/{roles,limits,merges,merges/{id}/diff|apply|reject,runs}`; lazy `backend.subagents`/
`get_team_merges`/`record_team_report`. New state: `caelo_subagents.json` (roles+limits) + `worktrees/`
(both gitignored). Renderer: **TeamView** ([`components/code/TeamView.tsx`](desktop/src/renderer/src/components/code/TeamView.tsx),
pure state in [`lib/teamView.ts`](desktop/src/renderer/src/lib/teamView.ts)) in the agent panel + an
**Extensions → Subagents** tab (role/limit config). Selfchecks: `agent_selfcheck.py` (139 → **166**:
isolation/roles/no-escalation/worktree/cascade/budget/merge/cost), `api_smoke.py` (217 → **228**:
`_unit_team_routes`). **Live delegation verified on the user's machine** (sandbox blocks xAI); don't
regress P0-1…P0-8 / M5–M6 / M13 / M14.

**Community packages = marketplace (M16, see [`docs/plans/zrealizowane/PLAN_M16_SPOLECZNOSC.md`](docs/plans/zrealizowane/PLAN_M16_SPOLECZNOSC.md)
+ [`docs/guides/PACKAGES.md`](docs/guides/PACKAGES.md)):** the M14 artifacts (skills/commands/MCP-configs/templates)
become **shareable, versioned packages** — distribution over M14, **zero hosted infrastructure** (git/
GitHub registry). A package is **`.caelopkg` = a ZIP** (`zipfile`, no new deps) with `manifest.json`
(name/version/type/author/`requires`/declared **permissions**/`source`/**sha256 integrity**) + `payload/`.
[`caelo_core/packages/`](caelo_core/packages/): `manifest.py` (validate/version-compare/`requirement_satisfied`/
`compute_integrity`/Zip-Slip-safe names) + `manager.py` `PackageManager` (build/export, **`inspect`** =
consent card with no install, **`install(consent=True)`**, registry parse/fetch, templates, `check_updates`).
**Security = the M14 regime, import runs NOTHING:** skills install **disabled** (not injected), MCP servers
install **disabled** (`enabled=False` so autostart skips them; start stays a separate gated action),
commands are just prompt templates, templates only write files via "New project". `install` refuses without
explicit consent AND on integrity mismatch (tamper); hard caps on size/files + Zip-Slip rejection. Secrets
(`authorization`/`env`) are **stripped on export**. Built-in **project templates** (`packages/templates/builtin/`
Ren'Py VN starter + DAZ pipeline, packaged via the spec like builtin skills) instantiate into a chosen dir →
`set_workspace` → an M9-B5 project (no overwrite of existing files). New state: `caelo_packages.json` (installed
registry) + `templates/` (user templates) — both gitignored. Routes [`routes/packages.py`](caelo_core/routes/packages.py):
`/packages` (list), `/inspect`, `/install`, `DELETE /{id}`, `/export`, `/registry`, `/updates`, `/templates`,
`/templates/{id}/new-project`; lazy `backend.packages` (injects `commands`+`mcp` so installs hit the same
registries as M14). Renderer: **Extensions → Marketplace** tab ([`components/extensions/Marketplace.tsx`](desktop/src/renderer/src/components/extensions/Marketplace.tsx):
Browse/Installed/Import/Templates + **ConsentCard**) + **Share/Export** buttons on the Skills/Commands/MCP/
Templates panels (`lib/packages.ts` for base64 ↔ file). Community ops: `.github/ISSUE_TEMPLATE/`
(package-submission + package-report), `docs/guides/PACKAGES.md`, `docs/guides/registry.example.json`. Selfchecks:
[`caelo_core/tools/packages_check.py`](caelo_core/tools/packages_check.py) (**47/47**: round-trip, consent,
tamper, Zip-Slip/limits, registry, updates, templates) + `api_smoke.py` `_unit_packages`. **Real network
registry/install verified on the user's machine** (sandbox blocks the net); don't regress P0-1…P0-8 / M5–M6 /
M13 / M14.

**Quality round (M18, SWOT remediation — see [`docs/plans/zrealizowane/PLAN_NAPRAWY_3.md`](docs/plans/zrealizowane/PLAN_NAPRAWY_3.md), 8/8 done):**
a maintenance round (no P0) hardening testability/maintainability after M9–M17. **Structural fact:** `state.py`
was **decomposed** (691→378 lines) — the **auth layer** moved to [`caelo_core/auth_tokens.py`](caelo_core/auth_tokens.py)
(`require_token`/`ws_authorized`/`_ws_origin_ok`/`_warn_no_token`, testable without `Backend`; **re-exported**
from `state.py` so `from caelo_core.state import require_token/ws_authorized` still works), **media/generation**
to [`backend_media.py`](caelo_core/backend_media.py) `MediaMixin` (incl. `MAX_MEDIA_BYTES`/`VIDEO_*`/`requests`
— self-checks patch them at `caelo_core.backend_media`, not `state`), and **project knowledge** to
[`backend_collections.py`](caelo_core/backend_collections.py) `CollectionsMixin` — `class Backend(MediaMixin,
CollectionsMixin)`. **Tests:** backend self-checks now run via **pytest** ([`caelo_core/tests/`](caelo_core/tests/),
P3-13) and `api_smoke.py` is split into `_smoke_common.py` + `smoke_{chat,media,routes,core}.py` (each <600
lines). Frontend gained **React Testing Library** component tests (`desktop/test/components/`) + **Playwright
E2E** (`desktop/e2e/`, over `preview:web`+`devMock`). Electron now runs with **`sandbox: true`** (P2-14) and the
no-token dev escape logs per-request. Don't regress these; the `state`/`auth_tokens`/`backend_media` re-export
boundary keeps the public import API stable.

**Grok-CLI parity (M19, Tier-1/2/3 DONE — see [`docs/plans/zrealizowane/PLAN_M19_TIER1.md`](docs/plans/zrealizowane/PLAN_M19_TIER1.md) ·
[`docs/plans/zrealizowane/PLAN_M19_TIER2.md`](docs/plans/zrealizowane/PLAN_M19_TIER2.md) · [`docs/plans/zrealizowane/PLAN_M19_TIER3.md`](docs/plans/zrealizowane/PLAN_M19_TIER3.md);
analysis [`docs/plans/zrealizowane/PLAN_M19_PARYTET_GROK_CLI.md`](docs/plans/zrealizowane/PLAN_M19_PARYTET_GROK_CLI.md)):** adopts the strongest
bits of xAI's official Grok CLI (a Claude-Code fork). **Structural fact:** the agent's session wiring (lazy
`AgentSession` + `TeamManager` + `delegate` + M9 history record) was extracted from the WS handler into a
**transport-neutral [`AgentRunner`](caelo_core/agent/runner.py)** (§0) — `routes/agent.py` (WS), headless and
ACP all build the SAME runner with their own `emit`/`request_approval`/`stop` (do NOT re-add per-transport
wiring; extend `AgentRunner`). **[`__main__.py`](caelo_core/__main__.py) dispatches subcommands:** no args /
`serve` = uvicorn + handshake (Electron path — stdout stays clean, unchanged), `run` = headless, `acp` = ACP.
- **B1 headless** ([`caelo_core/headless.py`](caelo_core/headless.py)): `python -m caelo_core run -p "…"
  [--output-format plain|json|streaming-json] [--model] [--cwd] [--max-turns] [--tools/--disallowed-tools]
  [--permission-mode] [--always-approve] [--allow/--deny] [-s/-r/-c]`. Fail-closed (`request_approval`→reject;
  mutations only via bypass/accept-edits or an allow rule). Minimal session persistence in `DATA_DIR/sessions/`.
- **B2 ACP** ([`caelo_core/acp/`](caelo_core/acp/) `server.py`+`bridge.py`): `python -m caelo_core acp` →
  Agent Client Protocol over stdio (JSON-RPC 2.0, newline-delimited) for Zed/Neovim/Emacs. Server is also a
  client for `session/request_permission` (id-correlated, like `McpClient`). Frames→`session/update` via `bridge`.
- **B3 LSP** ([`caelo_core/lsp/`](caelo_core/lsp/) `client.py`+`manager.py`): ⚠ **Content-Length framing**
  (binary stdio, NOT newline-delimited like MCP). Agent tool `lsp` (READONLY — in `permissions.READONLY`;
  **hidden when no server configured**) + **passive diagnostics** after edits (new WS frame `diagnostics`).
  Config `lsp.json` (global `DATA_DIR` + project `<ws>/.caelo/lsp.json`); `backend.get_lsp()` is workspace-aware
  (rebuild on root change, like checkpoints) + `reload_lsp()`; REST [`routes/lsp.py`](caelo_core/routes/lsp.py);
  renderer **Extensions → Language Servers**. Editor inline squiggles deferred (diagnostics shown in agent panel).
  ⚠️ **Diagnostics are matched by `client.canon_key()`, NOT raw URI** (LIVE-verified): a server (e.g. pyright on
  Windows) publishes `publishDiagnostics` under `file:///g%3A/…` (lowercase drive, `:`→`%3A`) while our
  `path_to_uri` yields `file:///G:/…`; keying `_diagnostics` by canonical path (`normcase`/`normpath`) is the
  only thing that makes diagnostics show up — don't revert to raw-URI keying. `DEFAULT_DIAGNOSTICS_WAIT_S`
  is best-effort (loop breaks as soon as results arrive; first publish may be empty → short grace).
- **B4 glob permission rules** ([`agent/permission_rules.py`](caelo_core/agent/permission_rules.py)
  `RuleSet`): `ToolPrefix(glob)` (`Bash(npm*)`/`Edit(src/**)`/`Read`/`Grep`/`Write`/`WebFetch(domain:…)`/
  `MCPTool`), **deny>allow**, segment-aware `*`/`**` (path) vs flat (command/name). A layer ABOVE the
  "Always allow" allowlist: **deny** is a hard refuse in `session._handle_tool_call` (covers READONLY + bypass),
  **allow** auto-accepts in `_gate_mutation` — **P0-1 preserved** (a `Bash(...)` allow never bypasses
  metachars). Rules from `caelo_settings.json` + `<ws>/.caelo/permissions.json` + CLI `--allow/--deny` +
  `PUT /permissions/rules`; `backend.reload_permission_rules()`.
- **Tier-2 DONE** ([`docs/plans/zrealizowane/PLAN_M19_TIER2.md`](docs/plans/zrealizowane/PLAN_M19_TIER2.md)): **B5 ecosystem interop** — the agent
  reads `AGENTS.md`/`CLAUDE.md` next to `CAELO.md` (`agent/caelomd.py`), `McpManager` merges `~/.claude.json`+
  `.mcp.json` servers (imported `enabled=False`), skills are discovered from `~/.claude/skills`. **B6
  orchestration-skills** — new roles + `skills/builtin/` packages that drive `delegate` (implement/review/design/
  best-of-n/check-work/pr-babysit). **B7 OS-sandbox** ([`caelo_core/sandbox/`](caelo_core/sandbox/) `profiles.py`+
  `wrap.py` — macOS seatbelt / Linux bwrap, wired into `run_command` + MCP + LSP spawns). **B8 hybrid-memory**
  ([`caelo_core/memory.py`](caelo_core/memory.py) + [`embeddings.py`](caelo_core/embeddings.py): `/v1/embeddings`
  + an `event_embeddings` table with kNN/`hybrid_search` in `history_store`, injected via `session._maybe_inject_memory`).
- **Tier-3 DONE** ([`docs/plans/zrealizowane/PLAN_M19_TIER3.md`](docs/plans/zrealizowane/PLAN_M19_TIER3.md), quick-wins): **B9 effort** (`reasoning.effort`
  in `responses_client`/`llm`, per-role + `EffortSelect.tsx`; **reasoning_effort is MODEL-DEPENDENT** —
  grok-4.3 / grok-4.20-*reasoning support `none/low/medium/high`, but grok-4 / grok-build-* / grok-3 (non-mini)
  return 4xx if it's sent, so **both clients retry ONCE without it on 400/422** — effort is best-effort and a turn
  never breaks on an unsupporting model; the UI warns via `lib/modelCaps.modelSupportsEffort` in `EffortSelect`),
  **B10 export-md + auto-compact** (`lib/exportMarkdown.ts`,
  `/history/export`, `--export-md`; deterministic `compact_history`, off by default), **B11 personas + I/O contract**
  (`roles.py` instructions/inputs/outputs → subagent `extra_system`), **B12 real git worktree** (`worktree.py`
  `use_git` branch, used by `team.py`), **B13 web_fetch** (`tools.web_fetch`, https-only + SSRF guard; `web_search`
  deferred), **B14 hierarchical project config** ([`agent/project.py`](caelo_core/agent/project.py) deeper-wins
  chain feeding CAELO.md / permission rules / LSP / sandbox).
- **Selfchecks:** `agent_selfcheck` 166 → **184** (B4), then extended with Tier-2/3 B-item tests (CAELO.md interop ·
  orchestration roles · memory injection · effort · persona/IO · auto-compact · git worktree · web_fetch · project
  config); new **`headless_check`** (19, B1), **`acp_check`** (14, B2), **`lsp_check`** (19, B3, Content-Length mock
  server `tools/_lsp_mock_server.py`), **`sandbox_check`** (29, B7), **`embeddings_check`** (11, B8); `mcp_check`
  24 → **36** (B5 interop), `history_check`/`api_smoke` extended (+`/permissions/rules`/`/lsp` routes). Pytest wraps
  the suites (`tests/test_selfchecks.py`; install `requirements-dev.txt` for the adapter). New gitignored state:
  `sessions/` (B1), `lsp.json` (B3), `sandbox.json`/`sandbox-events.jsonl` (B7). ⚠ **LIVE verification still pending
  on the user's machine** (sandbox blocks xAI/exec): real `run -p`, ACP in Zed/Neovim, real LSP/embeddings/seatbelt-
  bwrap/`web_fetch`. The **B0 `cli-chat-proxy` spike is NOT started** (separate experiment in
  `PLAN_M19_PARYTET_GROK_CLI.md` §7). Don't regress P0-1…P0-8 / M5–M6 / M13 / M14.

## Commands

All paths below are relative to the repo root. The frontend npm scripts run from `desktop/`.

**Dev (run the app):**
```powershell
# one-time backend venv (in network with TLS interception add: --trusted-host pypi.org --trusted-host files.pythonhosted.org)
cd caelo_core; python -m venv .venv; .venv\Scripts\pip install -r requirements.txt; cd ..
# NOTE: requirements now includes `regex` (P0-3 ReDoS-safe grep). Re-run the pip line above if you have an existing venv.
cd desktop; npm install         # one-time
npm run dev                     # Electron + Vite HMR; main process spawns the sidecar
```
Electron finds Python in this order: `CAELO_CORE_PYTHON` env → `caelo_core/.venv/Scripts/python.exe`
→ system `python`. Override: `$env:CAELO_CORE_PYTHON = "C:\path\python.exe"; npm run dev`.

**Gotcha — `npm run dev` fails with `Error: Electron uninstall` (TLS-interception networks):**
this means the **Electron binary never downloaded** during `npm install` (Electron's postinstall fetches
`electron-vX-win32-x64.zip` from GitHub; a TLS-intercepting proxy blocks it — same class of issue as the pip
note above). The JS package is installed but `desktop/node_modules/electron/{dist/,path.txt}` are missing.
electron-vite's `getElectronPath` (NOT Electron's) reads `node_modules/electron/path.txt` + `dist/` and
ignores `ELECTRON_OVERRIDE_DIST_PATH` — it only honors `ELECTRON_EXEC_PATH` (full path to `electron.exe`).
Fixes, in order of preference:
1. **Root cause:** `$env:NODE_EXTRA_CA_CERTS = "C:\corp-root-ca.pem"` then `node desktop\node_modules\electron\install.js`
   (lets Node trust the intercepting proxy's cert; also fixes Playwright/other downloads).
2. **Manual binary:** download `electron-v<ver>-win32-x64.zip` (the version in `desktop/package.json`) via a
   browser, unzip, then make `node_modules/electron` self-contained: copy the unzip into
   `node_modules/electron/dist/` and write `node_modules/electron/path.txt` containing exactly `electron.exe`
   (no trailing newline). Survives new terminals + packaging; **wiped by the next `npm install`/`npm ci`**.
3. **Quick (ephemeral):** `set ELECTRON_EXEC_PATH=C:\…\electron.exe` (cmd) in the same shell as `npm run dev`.

**Type-check the frontend (primary check) + ESLint + Vitest + E2E:**
```powershell
cd desktop; npm run typecheck   # tsc for both node (main/preload) and web (renderer)
npm run lint                    # ESLint flat config (eslint.config.mjs), react-hooks rules only
npm test                        # Vitest: pure renderer utils + React component tests (desktop/test/)
npm run test:e2e                # Playwright E2E over preview:web + devMock (needs `npx playwright install chromium`)
```
ESLint is **deliberately narrow** — only `react-hooks` rules, not the full recommended sets. Vitest tests
live in `desktop/test/` (outside the tsconfig include, so they don't affect `typecheck`): **pure utils**
(`test/*.test.ts`, node env) + **React component tests** (`test/components/*.test.tsx`, jsdom via per-file
`// @vitest-environment jsdom` docblock — React Testing Library, P3-11). **E2E** specs live in `desktop/e2e/`
(Playwright over `preview:web`+`devMock`; `_mock.ts` stubs the backend via `page.route()`; restricted
networks set `E2E_CHROMIUM_PATH`). All lint/test/E2E devDeps (`eslint`/`vitest`/`@testing-library/*`/
`@playwright/test`) are now in `package.json`+lockfile (M18: P3-10/P3-11), so `npm ci` installs them.

**Backend self-checks (this repo's "tests"): run all via pytest (M18: P3-13), or each script standalone.**
```powershell
caelo_core\.venv\Scripts\pip install -r caelo_core\requirements-dev.txt   # one-time: pytest
caelo_core\.venv\Scripts\python -m pytest caelo_core\tests -v             # all 11 suites (discovery)
caelo_core\.venv\Scripts\python -m pytest caelo_core\tests -k api_smoke   # one suite (-k filter)
# …or run any suite standalone (each tools/*_check.py + api_smoke/handshake_check has a main()):
caelo_core\.venv\Scripts\python caelo_core\tools\handshake_check.py   # handshake + /health + token auth
caelo_core\.venv\Scripts\python caelo_core\tools\agent_selfcheck.py   # agent tools + loop (mocked LLM)
caelo_core\.venv\Scripts\python caelo_core\tools\sidecar_smoke.py     # packaged-sidecar smoke (after pack:sidecar; NOT in pytest)
```
`api_smoke` is split into `_smoke_common.py` + `smoke_{chat,media,routes,core}.py` (M18: P3-13, each < 600
lines); `api_smoke.main()` orchestrates them. The pytest adapter (`caelo_core/tests/test_selfchecks.py`)
wraps every suite (`sidecar_smoke` excluded — needs the packaged exe). They use mocks where xAI is needed.

**Run the backend standalone (from the repo root, not from `caelo_core/`):**
```powershell
caelo_core\.venv\Scripts\python -m caelo_core
```

**Packaging (.exe installer — Windows):**
```powershell
cd desktop
npm run pack:sidecar   # PyInstaller onedir → ../dist/caelo-core/caelo-core.exe (from caelo_core/.venv)
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

- `caelo_config.json` — **owned exclusively by `HistoryManager`**, rewritten wholesale (history /
  chat_history / save_path only). Never write anything else here — it wipes the data.
- `caelo_settings.json` — API key (fallback), `auth_source` (auto/oauth/api_key — the hard source switch),
  chat/code model, system prompt, temperature, `recent_workspaces`, `current_project_id`,
  `chat_search_mode`/`chat_search_sources` (M10 live-search defaults).
- `caelo_auth.json` — OAuth tokens (gitignored; never commit).
- `caelo_chats.json` — legacy conversation store. **No longer written by the sidecar** (P2-8: `ChatStore`
  removed from `Backend`); chat conversations now live in the renderer's `localStorage` (`useConversations`).
  `chats_manager.py` stays in the root (reusable) but is not instantiated.
- `caelo_permissions.json` — agent "Always allow" allowlist (atomic writes, P1-11).
- `caelo_history.db` (M9) — SQLite+FTS5 hub backbone: artifacts + searchable history + projects +
  `collection_files` + `gen_jobs` (M11 generation queue) ([`caelo_core/history_store.py`](caelo_core/history_store.py)).
  Own file; **never** touch `caelo_config.json`. Corrupt → `.corrupt` backup (like the JSON readers).
  **M22 — chat vs code projects:** the M9-B5 single shared "project" was split via a `projects.kind`
  discriminator (`'chat'` | `'code'`) + per-project `instructions` (added by idempotent `ALTER TABLE` +
  backfill `root != '' → 'code'`). `set_workspace` now binds the folder to a **`kind='code'`** project
  WITHOUT changing the active CHAT project — `Backend._code_project_id` stamps `mode='code'` events while
  `current_project_id` is the chat project (`record_event` picks by mode). Chat/Gallery/History list only
  `kind='chat'` (`GET /projects` → `list_projects(kind='chat')`); chat projects are renamable/deletable
  (`PATCH`/`DELETE /projects/{id}`, delete cascades events/artifacts/gen_jobs/collection_files + docs dir)
  and their `instructions` are prepended to the chat system prompt (`routes/chat.py`). Renderer: the
  **ProjectSwitcher** is now the project manager (rename/instructions/knowledge/delete; absorbed the old
  `KnowledgePopover`), and chat conversations carry a `project_id` (renderer `localStorage`) so the chat
  list is scoped per project.
- `project_docs/<project_id>/` (M10-B5) — local "project knowledge" documents (xAI has no vector
  stores); served sandboxed via `/collections/files/{id}/content`, attached on demand ("Attach all").
- `caelo_mcp.json` / `caelo_commands.json` / `caelo_hooks.json` (M14) — MCP servers / user slash commands /
  hooks config. Own files; atomic writes + `load_json_or_backup`. `caelo_mcp.json` may hold server
  secrets (`authorization`/`env`) → gitignored (the `grok_*.json` net covers them).
- `caelo_audit.log` (M14-B5) — JSONL audit of tool calls/blocks/hook scripts (soft-rotated, gitignored).
- `skills/<id>/SKILL.md` (M14-B6) — user skill packages + `_state.json` (enabled set). Bundled examples
  live in `caelo_core/skills/builtin/` (packaged via the spec, read-only), NOT here.
- `caelo_subagents.json` (M17) — subagent role overrides + team limits. Own file; atomic writes +
  `load_json_or_backup`; caught by the `grok_*.json` net. Built-in roles live in code, not here.
- `worktrees/<runN>/<agent_id>/` (M17) — isolated copies of the workspace for mutating subagents
  (like the M13 checkpoint copy, no git). Discarded on merge/reject; gitignored (dev `DATA_DIR` = repo).
- `caelo_packages.json` (M16) — registry of installed community packages (id/type/version/integrity/
  permissions). Own file; atomic writes + `load_json_or_backup`; caught by the `caelo_*.json` net.
- `templates/<id>/` (M16) — user-installed project templates. Built-in templates live in
  `caelo_core/packages/templates/builtin/` (packaged via the spec, read-only), NOT here. Gitignored.
- `sessions/<id>.json` (M19-B1; extended) — agent coding-session history. Originally headless-only
  (`-s`/`-r`/`-c`); the store was extracted to [`caelo_core/agent/sessions.py`](caelo_core/agent/sessions.py)
  (format **v2**: `id`/`cwd`/`project_id`/`title`/`model`/`created_at`/`updated_at`/`history`, loader
  tolerates the old `{id,cwd,history}`) and is now ALSO used by the interactive WS agent: `AgentRunner`
  persists the full session after every turn (stamped with `current_project_id`, M9-B5), the WS protocol
  gained a `session` frame (resume by id / start new) and REST [`routes/sessions.py`](caelo_core/routes/sessions.py)
  (`GET /agent/sessions?project_id=` · `GET /agent/sessions/{id}` · `DELETE`) backs the **Sessions** menu
  in the agent panel (resume + per-project filter). Own files; atomic writes + `load_json_or_backup`;
  gitignored (`/sessions/`, dev `DATA_DIR` = repo). ⚠️ **`routes/agent.py` mints a FRESH session id on EVERY
  WS connection** (announced via the `session` frame on connect). The Code panel is lazy and **unmounts on
  tab switch** (same gotcha as M11 Hub-staged media), so the agent transcript would be lost; `AgentPanel`
  persists the *active* session id in **`hub.codeSessionId`** (only once it has a transcript, so the
  fresh-per-connect id can't clobber it) and **auto-resumes it on (re)mount** (`getAgentSession` +
  `setSession(sid)`, overriding the fresh id). State that must survive a tab switch lives in Hub, not panel `useState`.
- `lsp.json` (M19-B3) — GLOBAL language-server config; project config is `<ws>/.caelo/lsp.json` (read-only).
  `load_json_or_backup` + atomic writes; gitignored (`/lsp.json`, dev `DATA_DIR` = repo). Also read:
  `<ws>/.caelo/permissions.json` (M19-B4 project glob rules).

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
  installs a `window.caelo` stub from `lib/devMock.ts` under `import.meta.env.DEV && !window.caelo`
  (stripped from production), so you can eyeball the redesign without spawning the sidecar.
- The backend binds **127.0.0.1 only**; never expose it on a routable interface. REST uses
  `Authorization: Bearer <token>` (constant-time compare); WebSockets take the token in the query
  (`?token=`) because browser WS cannot set headers. **Both REST and WS are fail-closed** (WS: P0-8;
  REST `require_token`: P1-10): `state.ws_authorized` requires the token + an allowed `Origin`
  (loopback / `file://` / `null`), and with NO configured token **both deny** unless
  `CAELO_CORE_ALLOW_NO_TOKEN=1` is set (explicit dev opt-in; `server.py` logs a warning on startup).
  CORS is narrowed to dev loopback + packaged `file://` (P1-9), not `*`. The renderer ships a
  **CSP** meta (P2-10: source-restricted `connect-src`/`img-src`/…), and `main/index.ts` blocks
  off-origin navigation (`will-navigate`) and allows only `media` permission requests (mic).
- **Shared backend helpers** (reuse them, don't reinvent). M1/M2: `caelo_core/errors.py`
  `upstream_error()` (log raw exc → return generic detail; use for xAI 5xx / `auth.py` so raw errors
  don't leak), `caelo_core/validation.py` (route input limits + data-URI validators, used in
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
