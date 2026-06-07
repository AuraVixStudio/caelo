"""Odkrycie korzenia projektu + hierarchiczny łańcuch katalogów config (M19-B14).

Domyka B5 (interop): obok globalnego `DATA_DIR` i pojedynczego workspace czytamy
konfigurację z KAŻDEGO katalogu na ścieżce od **korzenia projektu** (najbliższy `.git`
w górę) **do** workspace — z zasadą *deeper-wins* (katalog bliżej workspace nadpisuje/
rozszerza dalsze). Dzięki temu workspace będący podkatalogiem monorepo dziedziczy
reguły/CAELO.md/`.caelo/*` przodków, a headless `--cwd` zagnieżdżone w repo „po prostu
działa". Gdy workspace JEST korzeniem repo (typowy GUI) lub nie ma repo — łańcuch to
sam workspace, więc zachowanie sprzed B14 jest niezmienione.

Leaf module (tylko stdlib) — importowalny zarówno z `agent/` (caelomd), jak i z
`state.py`/`sandbox/` bez ryzyka cyklu.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

_MAX_WALK_DEPTH = 40  # zdroworozsądkowy cap (anty-pętla na nietypowych FS / dowiązaniach)


def find_project_root(start, *, ceiling: Optional[str] = None) -> Path:
    """Walk w górę od `start` za katalogiem/plikiem `.git` → korzeń repo. Brak `.git`
    (do limitu / `GIT_CEILING_DIRECTORIES` / korzenia FS) → zwraca `start` (jako Path).
    `.git` może być katalogiem (repo) albo plikiem (worktree/submodule) — `exists()`
    łapie oba."""
    try:
        cur = Path(start).resolve()
    except OSError:
        return Path(start)
    if cur.is_file():
        cur = cur.parent

    ceilings = set()
    raw = ceiling if ceiling is not None else os.environ.get("GIT_CEILING_DIRECTORIES", "")
    for c in (raw or "").split(os.pathsep):
        c = c.strip()
        if c:
            try:
                ceilings.add(Path(c).resolve())
            except OSError:
                pass

    node = cur
    for _ in range(_MAX_WALK_DEPTH):
        try:
            if (node / ".git").exists():
                return node
        except OSError:
            break
        if node in ceilings or node.parent == node:
            break
        node = node.parent
    return cur  # brak .git → traktuj `start` jako korzeń


def project_dir_chain(ws_root, *, project_root=None) -> List[Path]:
    """Katalogi od korzenia projektu DO `ws_root` (włącznie), **najpłytszy pierwszy**
    (deeper-wins ⇒ czytaj po kolei i nadpisuj/rozszerzaj). Gdy `ws_root` jest korzeniem
    repo / nie ma repo / `project_root` nie jest jego przodkiem → `[ws_root]` (bezpieczny
    fallback = zachowanie sprzed B14). `project_root` (opcjonalny) nadpisuje auto-odkrycie."""
    if not ws_root:
        return []
    try:
        ws = Path(ws_root).resolve()
    except OSError:
        return [Path(ws_root)]
    root = Path(project_root).resolve() if project_root else find_project_root(ws)

    chain = [ws]
    cur = ws
    for _ in range(_MAX_WALK_DEPTH):
        if cur == root or cur.parent == cur:
            break
        cur = cur.parent
        chain.append(cur)
    if chain[-1] != root:
        return [ws]  # root nie jest przodkiem ws → tylko workspace
    chain.reverse()  # najpłytszy (korzeń) pierwszy
    return chain
