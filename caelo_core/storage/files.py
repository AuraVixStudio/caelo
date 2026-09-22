"""Bezpieczny zapis workspace: pliki `.part`, atomowy rename i datowany kosz."""

from __future__ import annotations

import hashlib
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Iterable


class WorkspaceFileManager:
    def __init__(self, root) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def allocate(self, kind: str, extension: str) -> Path:
        ext = extension if extension.startswith(".") else f".{extension}"
        name = f"studio_{kind}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}{ext}"
        # Zgodność z klasycznym Caelo: użytkownik wskazuje folder wynikowy i gotowe
        # media trafiają bezpośrednio do niego. Struktury pomocnicze (biblioteka
        # referencji, jej miniatury) żyją w DATA_DIR aplikacji, nie w output-dir.
        return self.root / name

    def atomic_write(self, target, chunks: Iterable[bytes]) -> tuple[str, int]:
        target = self._inside(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".part")
        digest, total = hashlib.sha256(), 0
        try:
            with open(partial, "wb") as handle:
                for chunk in chunks:
                    if not chunk:
                        continue
                    handle.write(chunk)
                    digest.update(chunk)
                    total += len(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(partial, target)
        except Exception:
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        return digest.hexdigest(), total

    def trash(self, path) -> Path:
        source = self._inside(path)
        day = datetime.now().strftime("%Y-%m-%d")
        target_dir = self.root / ".trash" / day
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / source.name
        if target.exists():
            target = target.with_name(
                f"{target.stem}_{datetime.now().strftime('%H%M%S%f')}{target.suffix}"
            )
        shutil.move(str(source), str(target))
        return target

    def _inside(self, path) -> Path:
        result = Path(path).resolve()
        if result != self.root and self.root not in result.parents:
            raise ValueError("path escapes media workspace")
        return result
