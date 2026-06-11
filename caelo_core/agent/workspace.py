"""Katalog roboczy agenta + sandbox ścieżek.

Wszystkie operacje plikowe agenta i tras /fs są rozwiązywane względem korzenia
workspace i NIE mogą z niego uciec (ochrona przed `..`/ścieżkami absolutnymi).
"""

from __future__ import annotations

import os
from pathlib import Path


class WorkspaceError(Exception):
    pass


# 3.3-a: zarezerwowane nazwy urządzeń Windows — read_file("CON") przechodziło sandbox
# i WIESZAŁO wątek nieprzerywalnie (read_text na urządzeniu konsoli). Odrzucamy je
# na KOMPONENTACH przed resolve() (Path('CON').resolve() daje \\.\CON, więc string-match
# po resolve nie zadziała). Tylko na Windows — na POSIX to zwykłe nazwy plików.
_WIN_RESERVED = (
    frozenset({"CON", "PRN", "AUX", "NUL"})
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


class Workspace:
    def __init__(self, root: str) -> None:
        p = Path(root).expanduser().resolve()
        if not p.exists() or not p.is_dir():
            raise WorkspaceError(f"Workspace path is not a directory: {root}")
        self.root = p

    def resolve(self, rel: str | None) -> Path:
        """Rozwiązuje ścieżkę względną do workspace; odrzuca ucieczki poza korzeń."""
        rel = rel or "."
        if os.name == "nt":
            for part in Path(rel).parts:
                if Path(part).stem.upper() in _WIN_RESERVED:
                    raise WorkspaceError(f"Reserved device name not allowed: {rel}")
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
