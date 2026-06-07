# Caelo — User Guide

Caelo is a desktop client for **xAI's Grok** models: chat with live web/X search, image &
video generation, voice (TTS/STT/realtime), and an **agentic coding module** with local file
access — in the spirit of Claude Code / Codex. It runs as an **Electron** app talking to a
local **Python sidecar** that holds your credentials; **your API key never reaches the UI and
never leaves your machine**, and there is **no telemetry**.

> New here? Read **[Getting Started](#getting-started)** first, then jump to the module you need.
> Developers / integrators: see **[API.md](API.md)** for the REST/WebSocket reference.

---

## Table of contents

- [Getting Started](#getting-started)
- [Core concepts](#core-concepts) — Projects · Send-to · Costs · Privacy
- Modules: [Chat](#chat) · [Code (agent)](#code-agent) · [Image](#image) · [Video](#video) ·
  [Gallery](#gallery) · [Voice](#voice) · [History](#history) · [Extensions](#extensions) ·
  [Settings](#settings)
- [Troubleshooting](#troubleshooting)

---

## Getting Started

1. **Install / run.** Launch the installed app, or run from source (`cd desktop; npm run dev`).
   On start, the app spawns the local sidecar and shows a connection status in the lower-left
   rail: **Starting backend… → Connected**.
2. **Authenticate (one of two ways).** Open **Settings**:
   - **Sign in with xAI** (OAuth) — recommended; no key to paste, or
   - **API key** — paste an `xai-…` key from the xAI console (stored locally; never shown back).
   - You can also set `XAI_API_KEY` in a local `.env` as a fallback.
   - Precedence used by the backend: **OAuth token → saved API key → `XAI_API_KEY`**.
3. **(Optional) Create a Project.** Use the project switcher (top bar) to scope chats, media,
   and history together. See [Projects](#core-concepts).
4. **Start using a module** from the left rail (Chat, Code, Image, …).

> **Costs:** Caelo is *bring-your-own-key* — every request bills your xAI account. Modules that
> can spend money (Image, Video, Voice) show an **estimate** before you run. Estimates are
> approximate; the authoritative cost is on your xAI dashboard.

---

## Core concepts

**Projects (chat).** A chat project is a container that scopes your chats, generated media, voice
turns and **History**, and can hold per-project **instructions** (a system prompt added to every
chat in that project) plus **knowledge** documents. Create, switch, rename, edit instructions,
manage knowledge and delete projects from the top-bar **project switcher** — the ⚙ on a project
opens its settings. New chats and the chat list are scoped to the active project. **Code workspaces
are separate (M22):** opening a folder in **Code** binds it to its own *code* project (for code
history) and does **not** change your active chat project, so code folders no longer clutter the
chat project list.

**Send-to.** Most results can be forwarded to another module — e.g. send a chat code block to
the **Code** agent, or send a generated image into **Video** as a source frame. Look for the
send/▾ action on cards and message blocks.

**Permission gate (agent).** The coding agent runs READ-ONLY tools freely, but **mutating
actions** (write file, edit file, run command, mutating MCP tools) require your approval via an
inline card. You can **Allow once** or **Always allow** a specific normalized command; the
allowlist is saved locally. See [Code](#code-agent).

**Privacy & security.** The backend binds to `127.0.0.1` only and is protected by a per-session
token. Your API key / OAuth token stay in the sidecar and are **never returned to the UI**.
No analytics or telemetry are collected. See the repo `SECURITY.md`.

---

## Chat

General conversation with Grok, backed by the **Responses API**.

**What you can do**
- **Live search.** Toggle search mode **Auto / On / Off**. When active, Grok can search the
  **web** and **X** and the reply shows **citations** (sources) you can open.
- **Vision.** Attach images (grok-4 family) and ask about them.
- **Document Q&A.** Attach a file, or use **project knowledge** ("Attach all") to ground answers
  in your project's documents (stored locally — see [Extensions ▸ knowledge](#code-agent) and the
  knowledge popover in the composer).
- **Slash commands.** Type `/` in the composer for prompt templates (e.g. `/plan`, `/review`,
  `/commit`, `/test`, `/mcp`, plus your own). The **Ctrl-K** palette runs the same commands.
- **Attachments & dictation.** Add files/images; click the mic to **dictate** (batch
  speech-to-text) straight into the composer.
- **Read aloud.** Play any reply with text-to-speech.
- **Usage counter.** Token usage / running cost is shown per conversation.

**Tips**
- Conversations are stored locally (in the renderer), scoped to the active project.
- Pick the chat model and default search mode in **Settings**.

---

## Code (agent)

A coding workspace with a Grok-powered agent that can read and modify files in a folder you
choose — sandboxed to that folder.

**Layout**
- **File tree + editor** (CodeMirror) — browse and edit files.
- **Git panel** — status, diff, stage (add), commit.
- **Agent panel** — chat with the agent; it plans, edits, and runs commands with your approval.
- **Terminal** — an embedded shell (requires `pywinpty` in the backend venv; the agent's own
  `run_command` tool works without it).

**Choose a workspace.** Click to select a folder. All agent file access is **sandboxed** to that
root — paths that escape (`..`, absolute, symlinks/junctions) are rejected. Recent workspaces are
remembered.

**Agent trust modes (M13)**
- **Plan** — the agent proposes a plan / diffs without applying.
- **Review / accept-edits** — changes surface as **diffs** you approve.
- Mutating tools (write/edit/run command, mutating MCP) always go through the **permission gate**:
  approve **once** or **Always allow** an exact command. Dangerous commands are blocked by a
  built-in hook regardless of the allowlist.

**Checkpoints & Undo (M13).** The agent snapshots files before changes; use **Undo** to roll back
to a checkpoint.

**Sessions (M21).** Conversations with the agent are **saved automatically** and can be **resumed**
with full context. Open the **Sessions** menu (top of the agent panel) to start a **New** session,
**reopen** a past one (its transcript is restored and the agent continues with the saved context),
or **delete** one. Filter the list by text or by **This project / All projects** (the current
folder).

**Subagent teams (M17).** For larger tasks the agent can **delegate** subtasks to specialized
roles (researcher / reviewer / implementer / tester). Mutating roles work in an **isolated copy**
of the workspace; their changes come back as **one reviewable diff** (with conflict detection) you
apply or reject in **TeamView**. Configure roles and limits in **Extensions ▸ Subagents**.

**Project CAELO.md.** A workspace-level `CAELO.md` lets you give the agent persistent instructions
(like project conventions); edit it from the agent panel.

---

## Image

Generate and edit images via a unified job queue (M11).

**Modes**
- **Text → image** — prompt only.
- **Edit** — prompt + reference image(s).
- **Variation** — produce variations of a reference.
- Up to **3 reference images** can be staged.

**How it works.** Submitting creates a **job** in the queue (queued → running → done/failed).
A **cost estimate** is shown before you run. Finished images are saved and registered as
**artifacts** (visible in **Gallery** and **History**), scoped to the active project. You can
**cancel** or **retry** jobs and clear finished ones.

---

## Video

Generate and edit video via the same job engine (M11). Long renders are polled **server-side**, so
you can keep working.

**Modes**
- **Text → video** and **Image → video** (stage a source image / first frame).
- **Edit** an existing video, or **Extend** it (add duration).
- Set duration, resolution, and aspect ratio where applicable.

**How it works.** Like Image: a queued job with a cost estimate, cancel/retry, and the result
saved as a project artifact. Because video can take minutes, the job stays "running" until the
render finishes or a deadline is reached.

---

## Gallery

A unified view of your generated **artifacts** (images and video).

- Filter by the active project.
- Open an artifact, reveal the file on disk, or **send** it to another module (e.g. an image into
  Video as a source).
- Delete an artifact to remove both the record and the file from disk.

---

## Voice

Four modes, selectable via the tabs at the top:

- **Speak (TTS).** Type text, pick a **voice** (5 options) and **language**, and synthesize audio.
  A character count and cost estimate are shown; play inline or open the saved file.
- **Transcribe (STT).** Upload/record audio and get a transcript (batch). Cost is derived from
  duration.
- **Talk.** A back-and-forth voice conversation: you speak, Caelo transcribes (live partials),
  answers via the Responses API (with the same search/tools as Chat), and speaks the reply.
  Say something while it's talking to **interrupt** (barge-in).
- **Live.** A low-latency realtime voice mode (Voice Agent).

Audio flows **renderer → sidecar → xAI**; your key is injected by the sidecar and never reaches
the browser. A per-session cost accumulator tracks STT/TTS spend. Default voice and language live
in **Settings**.

> **Dictation** in Chat and the Code agent uses the **batch** STT path; the live partial transcript
> is the **Talk** mode.

---

## History

A searchable backbone of everything the hub produced (M9).

- **Full-text search** across events (chats, generations, voice turns) and artifacts.
- **Filter by project**.
- Open an item or **send** it to another module.
- Backed by a local SQLite database (`caelo_history.db`).

---

## Extensions

Make the hub programmable. Tools added here serve **both** Chat and the agent. Tabs:

- **Commands** — slash-command prompt templates (built-in `/plan /review /commit /test /mcp`
  plus your own). Surfaced in the Chat composer (`/`) and the Ctrl-K palette.
- **MCP** — connect **Model Context Protocol** servers to add tools. Starting a stdio server is
  an explicit, gated action; servers run hardened (scrubbed env, tree-kill). Secrets
  (`authorization`/`env`) are never shown back. Read-only tools run freely; mutating tools go
  through the permission gate (in chat they must be pre-approved).
- **Skills** — `SKILL.md` knowledge packages; enabled skills are injected into the agent's system
  prompt. Bundled general coding skills (commit, write-tests, refactor, debug, document-code,
  explain-codebase, plus multi-agent orchestrators like implement/review) plus your own.
- **Hooks** — deterministic `pre_tool` / `post_tool` / `pre_session` hooks (e.g. block-dangerous-
  commands, audit-all, auto-format after write). Includes an **audit log** viewer.
- **Subagents** — define agent **roles** (tool scope, worktree, persona, model) and team **limits**
  (parallelism, budgets, timeouts). Used by the Code agent's **delegate** feature.
- **Marketplace** — share/install community **packages** (`.caelopkg`): skills, commands, MCP
  configs, and project templates.
  - **Browse / Installed / Import / Templates** sub-tabs.
  - **Import shows a Consent Card** listing the package's declared permissions and integrity
    (sha256) **before** anything is installed. Installs run **nothing**: skills install **disabled**,
    MCP servers install **disabled** (won't autostart), commands are just templates, templates only
    write files when you start a new project from them.
  - **Templates** (e.g. Ren'Py VN starter, DAZ pipeline) instantiate into a folder and become a
    project. Existing files are never overwritten.

---

## Settings

- **Authentication** — Sign in with xAI (OAuth) or paste an **API key** (stored locally; only a
  `has_api_key` flag is ever returned). Sign out.
- **Models** — choose the **chat** model and the **code/agent** model.
- **System prompt** and **temperature** for chat.
- **Live search defaults** — default search mode and sources for Chat.
- **Voice defaults** — default voice and language.
- **Workspaces** — recent code workspaces; the current project.
- **Output directory** — where generated media is saved.
- **Theme** — light / dark / system (toggle in the rail).

---

## Troubleshooting

- **Stuck on "Starting backend…" / "Connection error".** The sidecar failed to start or was
  killed. The app retries automatically (up to a few times) and restarts it on crash. If it
  persists, check that Python is available (dev: `caelo_core/.venv`), or set
  `CAELO_CORE_PYTHON` to a specific interpreter.
- **"Server is running without a session token" (401).** The backend is fail-closed without a
  token. In normal use Electron provides one automatically; this only appears in unusual dev
  setups.
- **Terminal tab does nothing.** Install `pywinpty` in the backend venv. The agent's
  `run_command` tool does not require it.
- **Live search / vision / generation errors.** These need valid credentials and network. Verify
  you're authenticated (Settings) and that your xAI account has access/credits.
- **Microphone not working in Voice.** Grant the microphone permission when prompted (the app
  only requests `media` and `fullscreen`).

---

*This guide describes end-user features. For the HTTP/WebSocket surface (96 REST routes + 6
WebSocket endpoints), see **[API.md](API.md)**. All user-facing UI text is in English by project
convention.*
