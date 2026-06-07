"""Trasy systemu plików workspace (drzewo, odczyt, zapis ręczny) — dla mini-IDE.

Zapis przez /fs/write jest BEZPOŚREDNI (ręczny zapis użytkownika w edytorze) —
zatwierdzanie dotyczy tylko zmian agenta (WS /agent/stream).
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from caelo_core.agent.tools import IGNORE_DIRS, atomic_write_text
from caelo_core.agent.workspace import WorkspaceError
from caelo_core.state import Backend, get_backend, require_workspace

router = APIRouter(prefix="/fs", tags=["fs"])

# Cap na płaski spis plików (@-odwołania w composerze agenta) — duże repo nie zaleją UI.
MAX_FS_FILES = 5000


class WorkspaceReq(BaseModel):
    path: str


class WriteReq(BaseModel):
    path: str
    content: str


@router.get("/workspace")
def get_workspace(b: Backend = Depends(get_backend)) -> dict:
    ws = b.get_workspace()
    return {"path": ws.root.as_posix() if ws else None}


@router.post("/workspace")
def set_workspace(req: WorkspaceReq, b: Backend = Depends(get_backend)) -> dict:
    try:
        ws = b.set_workspace(req.path)
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"path": ws.root.as_posix()}


@router.get("/recent")
def recent(b: Backend = Depends(get_backend)) -> dict:
    """Ostatnio otwierane workspace (do szybkiego przełączania folderów)."""
    return {"recent": b.recent_workspaces()}


@router.get("/tree")
def tree(path: str = ".", ws=Depends(require_workspace)) -> dict:
    try:
        target = ws.resolve(path)
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Not a directory")
    entries = []
    for e in sorted(target.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
        # P0-7: pomiń wpisy wychodzące poza workspace (symlink/junction na zewnątrz).
        try:
            ws.resolve(ws.rel(e))
        except WorkspaceError:
            continue
        entries.append({"name": e.name, "type": "dir" if e.is_dir() else "file", "path": ws.rel(e)})
    return {"path": ws.rel(target), "entries": entries}


@router.get("/files")
def files(ws=Depends(require_workspace)) -> dict:
    """Płaski, rekurencyjny spis plików workspace (POSIX, względny) — do @-odwołań
    w composerze agenta. Pomija IGNORE_DIRS i dowiązania (jak glob agenta), capped
    do MAX_FS_FILES (`truncated=True`, gdy ucięto). Sortowany dla stabilnego UI."""
    root = str(ws.root)
    out: list[str] = []
    truncated = False
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in IGNORE_DIRS and not os.path.islink(os.path.join(dirpath, d))
        )
        for fn in sorted(filenames):
            p = os.path.join(dirpath, fn)
            if os.path.islink(p):
                continue
            out.append(os.path.relpath(p, root).replace(os.sep, "/"))
            if len(out) >= MAX_FS_FILES:
                truncated = True
                break
        if truncated:
            break
    return {"files": out, "truncated": truncated}


@router.get("/read")
def read(path: str, ws=Depends(require_workspace)) -> dict:
    try:
        p = ws.resolve(path)
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not p.is_file():
        raise HTTPException(status_code=404, detail="Not a file")
    return {"path": ws.rel(p), "content": p.read_text(encoding="utf-8", errors="replace")}


@router.post("/write")
def write(req: WriteReq, ws=Depends(require_workspace)) -> dict:
    try:
        p = ws.resolve(req.path)
        atomic_write_text(p, req.content)  # P0-7: zapis atomowy
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "path": ws.rel(p)}
