# Changelog

All notable changes to **Caelo** are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] — 2026-06-23

First update after the initial release — a stabilization pass driven by live
verification against the real xAI API, plus two model/cost improvements.

### Added
- **Real per-request cost.** Chat (Responses API) and batch speech-to-text now show
  the **actual** cost reported by xAI (`usage.cost_in_usd_ticks`) instead of a local
  estimate, when the API provides it. Estimates remain as a fallback. Image/video and
  text-to-speech still use estimates.

### Changed
- **Video model:** switched the default to the stable **`grok-imagine-video-1.5`**
  (xAI dropped the `-preview` suffix). Edit/extend still routes to the base
  `grok-imagine-video`, which supports those operations.
- **Voice — Talk mode** now drives its transcription via batch speech-to-text with a
  local voice-activity detector (auto-stop on silence). This is reliable today; live
  partial transcripts are deferred until the streaming-STT rewrite lands.

### Fixed
- **Voice:** the audio worklet (mic capture for Talk/Live/STT) failed to load under the
  Content-Security-Policy — `script-src` now allows `blob:`, so voice capture works.
- **Settings:** save confirmations now appear as a toast instead of a banner off-screen.
- **MCP:** enabled servers auto-start and warm-start with the sidecar; the agent keeps
  its MCP tools after a workspace rebuild; stdio servers start in the workspace root so
  relative paths resolve.
- **Coding agent:** a session now survives switching tabs (auto-resume); a loop guard
  ends a turn cleanly when the model repeats an identical failing edit; LSP diagnostics
  now match on Windows (canonical-path keying) so squiggles show up.
- **Subagents / Team:** the merge-review diff opens in a modal (buttons always reachable)
  and the Team panel scrolls instead of compressing its cards.

## [0.1.0] — 2026-06-17

Initial public release.

- **Five modes under one hub:** Chat (Responses API with live web/X search, vision,
  document Q&A, citations), Image & Video generation/editing (unified job queue + gallery),
  Voice (TTS / STT / realtime "Live" / "Talk" pipeline), an agentic **Code** module
  (sandboxed file tools, diff approval, 4 trust modes, checkpoints/undo, `CAELO.md` rules,
  subagents/teams), and History/Gallery.
- **Bring-your-own-key**, loopback-only backend, no telemetry. OAuth (xAI account) or API key.
- **Extensibility:** MCP client (stdio + native remote), slash commands, hooks, skills,
  a community package marketplace, headless CLI, ACP and LSP integration.
- Electron (frontend) + Python FastAPI sidecar (backend); Windows installer, signed.

[0.1.1]: https://github.com/AuraVixStudio/caelo/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/AuraVixStudio/caelo/releases/tag/v0.1.0
