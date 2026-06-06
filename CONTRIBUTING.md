# Contributing to Caelo

Thanks for your interest in improving Caelo — an independent, open-source desktop
client for the xAI Grok API (chat, image/video generation, voice, and an agentic
coding module). Contributions of all kinds are welcome.

## Before you start

- Read [`README.md`](README.md) for what Caelo is and how to run it.
- Read [`CLAUDE.md`](CLAUDE.md) — it is the architecture source of truth
  (monorepo layout, the shared xAI core at the repo root, the sidecar handshake,
  data-file ownership rules, and the security model). A few rules there are
  load-bearing; please don't regress them.
- Be ready to sign the **Contributor License Agreement** — see
  [`CLA.md`](CLA.md). The first time you open a pull request, an automated check
  will ask you to sign; PRs cannot be merged without it.
- This is BYO-key software: **never** commit secrets (`caelo_auth.json`, `.env`,
  API keys). See [`SECURITY.md`](SECURITY.md).

## Development setup

Requirements: **Node.js ≥ 20** (tested on 22) and **Python 3.10+** (tested on
3.10/3.11). Windows is the primary platform today; the codebase is
platform-neutral (see M15) and mac/Linux are buildable on demand.

```powershell
# Backend sidecar — isolated venv
cd caelo_core
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt   # or -r requirements.lock for pinned versions
cd ..

# Frontend (Electron + React)
cd desktop
npm install            # one-time (or after dependency changes)
npm run dev            # launches Electron + Vite HMR; the main process spawns the sidecar
```

The main process finds Python in this order: `CAELO_CORE_PYTHON` env →
`caelo_core/.venv/Scripts/python.exe` → system `python`.

## Checks you must run (and that CI runs)

Caelo has no pytest — each backend self-check is a self-contained suite. Run from
the **repo root** (the sidecar imports the shared core via `python -m caelo_core`):

```powershell
# Backend (mock xAI; no network needed)
caelo_core\.venv\Scripts\python caelo_core\tools\handshake_check.py      # handshake + /health + token auth
caelo_core\.venv\Scripts\python caelo_core\tools\api_smoke.py            # REST + WS routes + token/CORS
caelo_core\.venv\Scripts\python caelo_core\tools\agent_selfcheck.py      # agent tools + loop + sandbox
caelo_core\.venv\Scripts\python caelo_core\tools\crossplatform_check.py  # PTY / tree-kill / paths per-OS
caelo_core\.venv\Scripts\python caelo_core\tools\mcp_check.py            # MCP client (mock stdio server)
caelo_core\.venv\Scripts\python caelo_core\tools\genjobs_check.py        # generation queue lifecycle
caelo_core\.venv\Scripts\python caelo_core\tools\history_check.py        # SQLite hub backbone

# Frontend
cd desktop
npm run typecheck      # tsc (node + web) — the primary frontend gate
npm run lint           # ESLint (react-hooks rules)
npm test               # Vitest unit tests for pure renderer utils
```

All of these run in CI on every pull request (see `.github/workflows/ci.yml`).
A red check blocks merge.

## Conventions (these override defaults)

- **All user-facing UI text MUST be in English** — every label, title, button,
  caption, tool/OAuth string. Code comments and docstrings may stay in the
  existing language (much of the codebase is Polish).
- **Do not use the "Grok" trademark in product naming/UI.** Caelo is the product;
  references to xAI / Grok are nominative only ("a client for the xAI Grok API").
- **SSE/streaming must be decoded as explicit UTF-8** (see the note in `CLAUDE.md`)
  — otherwise non-ASCII characters get mangled.
- **Do not move/rename the shared xAI core at the repo root** (`config.py`,
  `api_manager.py`, `oauth_manager.py`, `chats_manager.py`, `history_manager.py`).
  New backend code belongs in `caelo_core/`.
- **Keep it cross-platform.** Don't introduce new Windows-only dependencies;
  abstract platform-specific behavior (PTY, process kill, paths) — see M15.
- Reuse the shared helpers (`WsStream`, `scrubbed_env()`, `atomic_write_text()`,
  `load_json_or_backup()`, `upstream_error()`) rather than reinventing them.

## Pull request process

1. Fork and branch from `main`.
2. Make your change; add or update the relevant self-check / Vitest test.
3. Run the checks above locally — keep them green.
4. Open a PR with a clear description of *what* and *why*. Reference any issue.
5. Sign the CLA when prompted. Address review feedback.

By submitting a contribution you agree it is licensed under the project's
[Apache-2.0 license](LICENSE) and the terms of the [CLA](CLA.md).

## Sharing packages (skills, commands, MCP configs, templates)

Caelo has a community marketplace (M16): skills, slash commands, MCP server configs,
and project templates can be exported as a single `.caelopkg` file and shared, or
listed in a git-based registry. To build and publish one, or to submit it to the
registry, see [`docs/PACKAGES.md`](docs/PACKAGES.md). Two issue templates exist —
**Package submission** and **Report a problematic package** — under *New issue*.
Packages run under the same security regime as the rest of the app (declared
permissions, explicit consent, no auto-run).

## Code of Conduct

Participation in this project is governed by our
[Code of Conduct](CODE_OF_CONDUCT.md). Please be respectful.
