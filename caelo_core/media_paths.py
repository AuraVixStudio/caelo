"""Wspólny sandbox ścieżek mediów (S31-k / P2-3.2-b).

Które katalogi WOLNO serwować/kasować jako pliki mediów: `DATA_DIR` (baza/historia)
+ skonfigurowany folder zapisu. Plik spoza nich → odmowa (anty-traversal). Wydzielone
z `routes/history.py`, by `state.delete_project` mógł sprzątać pliki artefaktów tym
samym, sandboxowanym mechanizmem (bez cyklu importu routes↔state).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import config  # type: ignore  # repo-root (sys.path z caelo_core/__init__.py)


def media_bases(save_path: Optional[str] = None) -> list[Path]:
    """Dozwolone bazy mediów: DATA_DIR + (opcjonalnie) folder zapisu. P2-3.2-b: baza,
    która rozwiązuje się do KORZENIA systemu plików (C:\\ / /), jest ODRZUCANA — inaczej
    spreparowany `output-dir` poszerzyłby sandbox `/artifacts` na cały dysk."""
    bases = [Path(config.DATA_DIR)]
    if save_path:
        bases.append(Path(save_path))
    out: list[Path] = []
    for base in bases:
        try:
            r = base.resolve()
        except Exception:
            continue
        if r.parent == r or str(r) == r.anchor:  # korzeń FS — nie wpuszczaj
            continue
        out.append(r)
    return out


def within(path: Path, base: Path) -> bool:
    try:
        return path.is_relative_to(base)
    except Exception:
        return False
