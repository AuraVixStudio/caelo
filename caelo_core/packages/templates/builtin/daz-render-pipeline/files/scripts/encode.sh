#!/usr/bin/env bash
# Encode a DAZ Studio image sequence (renders/) into web-ready clips (output/).
# Edit these three values to match your render, then run from the project root.
set -euo pipefail

PATTERN="renders/render_%04d.png"   # zero-padded frame pattern
FRAMERATE=30                        # frames per second
BASENAME="output/clip"              # output base name (no extension)

mkdir -p output

# VP9 WebM — great quality, supports alpha (use yuva420p for transparent renders).
ffmpeg -y -framerate "$FRAMERATE" -i "$PATTERN" \
  -c:v libvpx-vp9 -b:v 0 -crf 30 -row-mt 1 -pix_fmt yuv420p \
  "${BASENAME}.webm"

# H.264 MP4 fallback — maximum compatibility.
ffmpeg -y -framerate "$FRAMERATE" -i "$PATTERN" \
  -c:v libx264 -crf 18 -preset slow -pix_fmt yuv420p \
  "${BASENAME}.mp4"

echo "Done: ${BASENAME}.webm and ${BASENAME}.mp4"
