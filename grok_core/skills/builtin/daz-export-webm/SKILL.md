---
name: DAZ — Export Render to WebM
description: Encode a DAZ Studio image-sequence render into a web-ready WebM (VP9) clip.
triggers: [daz, render sequence, webm, ffmpeg, image sequence]
---

# DAZ — Export Render to WebM

Use this when the user has a DAZ Studio image-sequence render (e.g. `render_0001.png …`)
and wants a web-ready video.

## Steps

1. Identify the frame sequence: directory, filename pattern (`render_%04d.png`), and
   the intended frame rate (ask if unknown; default 30 fps).
2. Confirm `ffmpeg` is available (`ffmpeg -version` via the agent's gated `run_command`).
   If not, tell the user to install it rather than guessing a path.
3. Encode to VP9 WebM with an alpha-safe, web-friendly setting. Run as separate,
   approval-gated commands (no shell chaining):
   - `ffmpeg -framerate 30 -i render_%04d.png -c:v libvpx-vp9 -b:v 0 -crf 30 -pix_fmt yuva420p out.webm`
   - For no-alpha renders use `-pix_fmt yuv420p` and consider `-row-mt 1` for speed.
4. Verify the output: report duration, resolution and size; offer an MP4 (H.264)
   fallback for compatibility if the user needs it.
5. Never delete the source frames unless the user explicitly asks.

## Notes

- Two-pass VP9 improves quality at a target bitrate; single-pass CRF is simpler and fine
  for most clips.
- Keep each `ffmpeg` invocation a single command so the approval card shows exactly what runs.
