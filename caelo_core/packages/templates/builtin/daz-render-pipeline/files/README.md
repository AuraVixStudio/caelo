# DAZ render pipeline

Created from the Caelo **DAZ — Render Pipeline** template. A simple, repeatable
layout for going from a DAZ Studio image sequence to a web-ready clip.

## Layout

```
renders/     # drop your DAZ image sequence here (render_0001.png, render_0002.png, …)
output/      # encoded clips land here
scripts/
  encode.sh  # ffmpeg one-liners (VP9 WebM + H.264 MP4 fallback)
```

## Use it

1. Render an image sequence from DAZ Studio into `renders/` using a zero-padded
   pattern such as `render_%04d.png`.
2. Make sure `ffmpeg` is installed (`ffmpeg -version`).
3. Run `scripts/encode.sh` (edit the frame rate / pattern at the top first).

The bundled **DAZ — Export Render to WebM** skill can drive this for you and explain
the trade-offs (alpha, CRF vs two-pass, MP4 fallback).
