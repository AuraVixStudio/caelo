"""Katalog roboczy agenta + sandbox ścieżek.

Wszystkie operacje plikowe agenta i tras /fs są rozwiązywane względem korzenia
workspace i NIE mogą z niego uciec (ochrona przed `..`/ścieżkami absolutnymi).
"""

from __future__ import annotations

import os
from pathlib import Path


class WorkspaceError(Exception):
    pass


class Workspace:
    def __init__(self, root: str) -> None:
        p = Path(root).expanduser().resolve()
        if not p.exists() or not p.is_dir():
            raise WorkspaceError(f"Workspace path is not a directory: {root}")
        self.root = p

    def resolve(self, rel: str | None) -> Path:
        """Rozwiązuje ścieżkę względną do workspace; odrzuca ucieczki poza korzeń."""
        rel = rel or "."
        candidate = Path(rel)
        full = (candidate if candidate.is_absolute() else (self.root / candidate)).resolve()
        if full != self.root and self.root not in full.parents:
            raise WorkspaceError(f"Path escapes workspace: {rel}")
        return full

    def rel(self, p: Path | str) -> str:
        try:
            return os.path.relpath(str(p), str(self.root)).replace(os.sep, "/")
        except Exception:
            return str(p)
