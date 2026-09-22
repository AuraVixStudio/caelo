# Security Policy

Caelo is a local-first, multi-provider desktop client. Credentials are stored on
your machine and are sent only to the provider selected for a request: xAI,
Google Gemini / Vertex AI, or OpenAI. We take their handling seriously and welcome
responsible disclosure.

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

- **Never commit `secrets.dat`, legacy `caelo_auth.json`, `.env`, API keys, or any
  `caelo_*.json` data file.** They are gitignored on purpose. `secrets.dat` is
  tied to the current OS user and is not a portable backup.
- The repository ships a **gitleaks** configuration (`.gitleaks.toml`) and a
  pre-commit hook; CI scans every push/PR for leaked secrets.
- If you ever accidentally commit a secret, **rotate it immediately** (revoke the
  affected provider key / re-authenticate) and tell the maintainers so history can be scrubbed
  before the change is published.

## Security model (what protects you)

These properties are part of the design and must not be regressed:

- **Loopback only.** The Python sidecar binds `127.0.0.1` exclusively — it is not
  reachable from the network.
- **Token auth, fail-closed.** REST uses a bearer token (constant-time compare);
  WebSockets take the token in the query string and validate the `Origin`. With no
  configured token, both REST and WS **deny** unless `CAELO_CORE_ALLOW_NO_TOKEN=1`
  is set explicitly (a logged dev opt-in).
- **OS-backed credential vault.** Saved xAI/Google/OpenAI keys and xAI OAuth tokens are
  encrypted by Electron `safeStorage` (DPAPI on Windows, Keychain on macOS, a
  supported Secret Service backend on Linux). The encrypted `secrets.dat` is
  written atomically; plaintext fields are removed from legacy settings/auth JSON.
- **Memory-only sidecar credentials.** Electron sends the decrypted snapshot over
  a private loopback channel authenticated by a separate token delivered through
  sidecar stdin. That token is not exposed by preload or placed in process arguments
  or environment variables. The sidecar never persists provider secrets.
- **Provider scope.** xAI credentials are sent only to xAI endpoints; Google API
  keys/ADC credentials only to Google endpoints; OpenAI keys only to OpenAI endpoints.
  `/settings` and `/auth/status`
  return presence/status flags, never credential values.
- **Scrubbed environment.** Agent `run_command`, the terminal PTY, and MCP
  subprocesses run with a secret-free environment (no `CAELO_CORE_TOKEN` /
  `XAI_API_KEY` / `OPENAI_API_KEY` / token-like vars).
- **Sandboxed file tools.** Agent file operations are confined to the workspace
  root (symlink/junction escapes rejected); mutating operations and shell commands
  require user approval.
- **Renderer hardening.** Content-Security-Policy meta, blocked off-origin
  navigation, and only the `media` (microphone) / `fullscreen` permissions granted.

See `CLAUDE.md` for the full architecture and the hardening history
(`docs/plans/PLAN_NAPRAWY.md`, `docs/plans/PLAN_NAPRAWY_2.md`).

## Telemetry

Caelo collects and transmits **no telemetry**. There is no analytics endpoint and
no usage reporting. Network traffic consists of requests to the xAI, Google or OpenAI
provider selected by the user, plus GitHub Releases for optional update checks.
Google Cloud ADC may independently use Google authentication endpoints when its
credential library refreshes a session. See the README's privacy section.

OpenAI Chat and Agent requests explicitly set `store: false`; Caelo keeps conversation
history locally and resends the required context. This does not mean the provider has
zero operational retention: OpenAI documents that abuse-monitoring logs may normally be
retained for up to 30 days. See [OpenAI — Your data](https://developers.openai.com/api/docs/guides/your-data).

## Supported versions

This is a young project under active development; only the latest release on the
default branch is supported. Please report against the most recent version.
