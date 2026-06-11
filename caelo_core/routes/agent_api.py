"""Trasy REST agenta (M13-B5): checkpointy / undo + edycja CAELO.md.

Spójne z WS `/agent/stream`: undo cofa to, co agent zsnapshotował w trakcie tury
(menedżer checkpointów jest współdzielony przez Backend — jeden mechanizm, jak
allowlista uprawnień). Fail-closed na tokenie (router montowany pod `require_token`).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import config  # type: ignore

from caelo_core.agent.caelomd import CAELO_MD_NAME, MAX_CAELO_MD_BYTES
from caelo_core.agent.tools import atomic_write_text
from caelo_core.agent.workspace import WorkspaceError
from caelo_core.state import Backend, get_backend, require_workspace

router = APIRouter(prefix="/agent", tags=["agent"])


# --- checkpointy / undo (M13-B3) ---
@router.get("/checkpoints")
def list_checkpoints(b: Backend = Depends(get_backend)) -> dict:
    cp = b.get_checkpoints()
    if cp is None:
        return {"checkpoints": [], "session_id": None, "partial": False,
                "has_workspace": False}
    data = cp.list()
    data["has_workspace"] = True
    return data


class UndoReq(BaseModel):
    # None → cofnij całą sesję (do najwcześniejszego checkpointu).
    checkpoint_id: Optional[str] = None


@router.post("/undo")
def undo(req: UndoReq, b: Backend = Depends(get_backend)) -> dict:
    cp = b.get_checkpoints()
    if cp is None:
        raise HTTPException(status_code=400, detail="No workspace selected")
    try:
        return cp.undo_to(req.checkpoint_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# --- CAELO.md (M13-B4/F4) ---
@router.get("/caelo-md")
def get_caelo_md(b: Backend = Depends(get_backend)) -> dict:
    """Treść workspace'owego CAELO.md (do edycji) + sygnał, czy istnieje globalny."""
    ws = b.get_workspace()
    if ws is None:
        raise HTTPException(status_code=400, detail="No workspace selected")
    p = ws.resolve(CAELO_MD_NAME)
    content = ""
    exists = p.is_file()
    if exists:
        content = p.read_text(encoding="utf-8", errors="replace")
    global_p = config.DATA_DIR / CAELO_MD_NAME
    return {"content": content, "exists": exists,
            "global_exists": global_p.is_file(), "max_bytes": MAX_CAELO_MD_BYTES,
            "name": CAELO_MD_NAME}


class CaeloMdReq(BaseModel):
    # P2-3.2-a: cap długości znakowej (GET deklaruje max_bytes, a strona odczytu i tak
    # truncuje na MAX_CAELO_MD_BYTES — bez tego zapis przyjmował dowolny rozmiar).
    content: str = Field("", max_length=MAX_CAELO_MD_BYTES)


@router.put("/caelo-md")
def put_caelo_md(req: CaeloMdReq, ws=Depends(require_workspace)) -> dict:
    """Zapisz workspace'owy CAELO.md (atomowo, sandbox). Wejdzie od następnej tury."""
    # Dodatkowo egzekwuj BAJTOWY budżet (UTF-8 wielobajtowy może przekroczyć cap znakowy).
    if len(req.content.encode("utf-8")) > MAX_CAELO_MD_BYTES:
        raise HTTPException(status_code=400,
                            detail=f"CAELO.md too large (> {MAX_CAELO_MD_BYTES // 1024} KiB)")
    try:
        p = ws.resolve(CAELO_MD_NAME)
        atomic_write_text(p, req.content)
    except WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "path": ws.rel(p)}
