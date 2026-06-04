"""Trasy systemu plików workspace (drzewo, odczyt, zapis ręczny) — dla mini-IDE.

Zapis przez /fs/write jest BEZPOŚREDNI (ręczny zapis użytkownika w edytorze) —
zatwierdzanie dotyczy tylko zmian agenta (WS /agent/stream).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from grok_core.agent.tools import atomic_write_text
from grok_core.agent.workspace import WorkspaceError
from grok_core.state import Backend, get_backend, require_workspace

router = APIRouter(prefix="/fs", tags=["fs"])


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
