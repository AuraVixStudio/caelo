# Changelog

All notable changes to **Caelo** are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.5] — 2026-08-12

Picks up xAI's August model wave — **Grok 4.6**, **reference-to-video**, and
**Grok Imagine Image 2.0** — and adds a third way to connect an MCP server:
a **local HTTP** one, with DAZ Studio 6 (SceneAgent MCP) in the catalogue.

### Added
- **Grok 4.6** (`grok-4.6`) is in the chat model list and is the new default. 500k context,
  vision, function calling, live web/X search, and a new **`xHigh`** reasoning level on top of
  low / medium / high. The context meter estimates 500k for it.
- **xHigh reasoning effort.** The effort selector offers it **only on models that document it**
  (today: `grok-4.6`) — picking a level a model doesn't know would silently fall back to its
  default, so the menu hides it instead, and warns if a previously chosen xHigh no longer applies
  after a model switch.
- **Reference images for video** (reference-to-video, `grok-imagine-video-1.5`). Attach up to
  **3** images in the Video panel to carry a character, outfit, or object into the clip and refer
  to them in the prompt as `<IMAGE_1>`…`<IMAGE_3>`. Unlike a first frame, they do **not** fix the
  opening shot — both can be used together. The tray only appears on models that accept them,
  and the references survive a tab switch like the other staged media.
- **Grok Imagine Image 2.0** (`grok-imagine-image-2.0`) in the image model list, with its
  **Quality** control (low / medium, xAI's default is medium). The control is shown only for 2.0 —
  it is the only model that accepts the parameter, and other models reject the whole request.
- **Local HTTP MCP servers** (`transport: "http"`). Beside stdio (a local process) and remote
  (executed on xAI's side), Caelo can now call a Streamable-HTTP MCP server **running on this
  machine**, with its tools going through the same permission gate as a local process. Server
  tokens are stored like other MCP secrets — the renderer only ever sees whether one is set, never
  its value — and a token is refused over plain `http://` to a non-loopback host.
- **DAZ Studio 6 in the MCP catalogue**, as two entries because the two editions differ in
  transport: **SceneAgent MCP (Pro)** over stdio — its bridge path is read from the installer's
  registry key and verified on disk, so the entry stays one-click — and **SceneAgent MCP
  (Plugin Edition)** over loopback HTTP, which takes the access token from the plugin's pane.

### Changed
- **Default chat model is now `grok-4.6`** (was `grok-4.5`). Saved per-session and per-setting
  choices are untouched, and the live model list from the API still wins over the built-in fallback.
- **Image cost estimates know 2.0** ($0.04 per image — twice the standard model, half of quality).
  The **default image model stays `grok-imagine-image`**: 2.0 is a deliberate choice, not a silent
  price increase.
- Servers imported from `~/.claude.json` with a **loopback** URL now arrive as local `http`
  servers instead of remote ones — xAI's cloud cannot reach this machine, so the old mapping
  produced a server that looked configured but could never run.

## [0.1.4] — 2026-07-13

Adds xAI's new flagship model, **Grok 4.5**.

### Added
- **Grok 4.5** (`grok-4.5`) is now in the chat model list and is the new default. Per xAI it is
  the most intelligent and fastest model, trained for coding, agentic tasks, and knowledge work
  (knowledge cutoff February 1, 2026). It supports adjustable `reasoning_effort` (low / medium /
  high, default high) — the effort selector works with it out of the box.

### Changed
- **Default chat model is now `grok-4.5`** (was `grok-4.3`). Existing per-session and saved model
  choices are unaffected; the live model list from the API still takes precedence over this
  built-in fallback list.
- The context-window meter now estimates **500k tokens** for `grok-4.5`.

## [0.1.3] — 2026-07-08

A creative-mode pricing/quality update, plus sturdier image inputs — and the first
macOS build produced and signed on Apple Silicon.

### Added
- **1080p video** on **`grok-imagine-video-1.5`**. The Video mode now offers 480p / 720p /
  1080p when the 1.5 model is selected (the base `grok-imagine-video` still tops out at 720p).

### Changed
- **Accurate video cost estimates.** Video is now priced **per resolution** to match xAI's
  tariff — 1.5: $0.08 / $0.14 / $0.25 per second at 480p / 720p / 1080p; base: $0.05 / $0.07 —
  instead of a single flat per-model rate.

### Fixed
- **Oversized image inputs no longer fail.** Reference images (Image mode) and the video first
  frame are now automatically compressed to WebP at the highest quality that still fits the API
  limit, instead of being rejected.
- **Readable errors.** Validation errors from the backend are shown as plain text instead of
  the unhelpful "[object Object]".

## [0.1.2] — 2026-07-03

A small usability update for the creative modes: reuse the prompt behind any
generated image or video without retyping it.

### Added
- **Reuse a saved prompt.** Every generated image and video already stores the prompt
  that made it; each artifact card (Gallery, and the "Recent" strips in the Image/Video
  modes) now surfaces it with a **Reuse prompt** button — one click drops the prompt
  into the matching mode (Image → Image, Video → Video) and takes you there — plus a
  **Copy** button. Long prompts are shown truncated with a **Show more** toggle to
  expand the full text.

### Fixed
- **Copy prompt** now works reliably in the packaged app: it falls back to a manual copy
  when the browser Clipboard API is unavailable or blocked.

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

[0.1.5]: https://github.com/AuraVixStudio/caelo/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/AuraVixStudio/caelo/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/AuraVixStudio/caelo/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/AuraVixStudio/caelo/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/AuraVixStudio/caelo/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/AuraVixStudio/caelo/releases/tag/v0.1.0
