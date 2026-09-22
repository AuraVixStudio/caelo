from __future__ import annotations

from pathlib import Path


def create_image_thumbnail(source, workspace_root, *, max_size=512, cache_key="") -> str:
    try:
        from PIL import Image

        source = Path(source)
        thumbnail_dir = Path(workspace_root) / "Thumbnails"
        thumbnail_dir.mkdir(parents=True, exist_ok=True)
        target = thumbnail_dir / f"{cache_key or source.stem}.webp"
        partial = target.with_name(target.name + ".part")
        with Image.open(source) as image:
            image.thumbnail((max_size, max_size))
            image.convert("RGB").save(partial, format="WEBP", quality=82)
        partial.replace(target)
        return str(target)
    except Exception:
        try:
            partial.unlink(missing_ok=True)  # type: ignore[possibly-undefined]
        except Exception:
            pass
        return ""
