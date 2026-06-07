# Security Policy

Caelo is a local-first desktop client. Your xAI credentials stay on your machine
("bring your own key", BYO-key) and are sent **only** to `api.x.ai`. We take the
handling of those credentials seriously and welcome responsible disclosure.

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report privately using **GitHub's "Report a vulnerability"** button under the
repository's *Security* tab (Private Vulnerability Reporting). If that is
unavailable, contact the maintainers through the repository's listed contact
channel.

Please include:

- a description of the issue and its impact,
- steps to reproduce (a proof of concept if possible),
- affected version / commit, and OS.

We aim to acknowledge reports within a few days and to provide a fix or
mitigation timeline after triage. Please give us a reasonable window to address
the issue before any public disclosure.

## Never commit secrets

- **Never commit `caelo_auth.json`** (OAuth tokens), `.env`, API keys, or any
  `caelo_*.json` data file. They are gitignored on purpose — keep them that way.
- The repository ships a **gitleaks** configuration (`.gitleaks.toml`) and a
  pre-commit hook; CI scans every push/PR for leaked secrets.
- If you ever accidentally commit a secret, **rotate it immediately** (revoke the
  xAI key / re-authenticate) and tell the maintainers so history can be scrubbed
  before the change is published.

## Security model (what protects you)

These properties are part of the design and must not be regressed:

- **Loopback only.** The Python sidecar binds `127.0.0.1` exclusively — it is not
  reachable from the network.
- **Token auth, fail-closed.** REST uses a bearer token (constant-time compare);
  WebSockets take the token in the query string and validate the `Origin`. With no
  configured token, both REST and WS **deny** unless `CAELO_CORE_ALLOW_NO_TOKEN=1`
  is set explicitly (a logged dev opt-in).
- **Key never leaves the host.** The xAI bearer token is sent only to `api.x.ai`;
  it is **never returned** by `/settings` (only `has_api_key`) and is **never**
  exposed to the renderer (the voice routes inject `Authorization` server-side).
- **Scrubbed environment.** Agent `run_command`, the terminal PTY, and MCP
  subprocesses run with a secret-free environment (no `CAELO_CORE_TOKEN` /
  `XAI_API_KEY` / token-like vars).
- **Sandboxed file tools.** Agent file operations are confined to the workspace
  root (symlink/junction escapes rejected); mutating operations and shell commands
  require user approval.
- **Renderer hardening.** Content-Security-Policy meta, blocked off-origin
  navigation, and only the `media` (microphone) / `fullscreen` permissions granted.

See `CLAUDE.md` for the full architecture and the hardening history
(`docs/plans/PLAN_NAPRAWY.md`, `docs/plans/PLAN_NAPRAWY_2.md`).

## Telemetry

Caelo collects and transmits **no telemetry**. There is no analytics endpoint and
no usage reporting. A fresh install talks only to `api.x.ai` (with your key) and to
GitHub Releases for update checks (which you can disable). See the README's
*Privacy & telemetry* section.

## Supported versions

This is a young project under active development; only the latest release on the
default branch is supported. Please report against the most recent version.
