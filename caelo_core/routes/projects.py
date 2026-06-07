"""Trasy projektów huba (M9-B5) — wspólny scope historii/artefaktów dla trybów.

  GET  /projects          — lista projektów + recent_workspaces (most) + aktywny id
  POST /projects          — utwórz (lub dla `root` reużyj) projekt i ustaw aktywnym
  POST /projects/current  — wybierz aktywny projekt (project_id=null czyści)

Aktywny projekt stempluje zdarzenia/artefakty (Backend.record_event/add_artifact),
więc przełączenie projektu zawęża `GET /history` i `GET /artifacts` (filtr project_id
z M9-B3). `recent_workspaces` są SUROWO surfacowane (kandydaci) — projekt powstaje
dopiero przy wyborze/otwarciu folderu (lazy, bez zaśmiecania). Token-guard w server.py.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from caelo_core import validation as V
from caelo_core.state import Backend, get_backend

router = APIRouter(prefix="/projects", tags=["projects"])


class CreateProjectReq(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    root: Optional[str] = Field(None, max_length=4096)


class SelectProjectReq(BaseModel):
    project_id: Optional[str] = Field(None, max_length=V.MAX_ID_LEN)


class UpdateProjectReq(BaseModel):
    # M22: zmiana nazwy / instrukcji projektu czatu (oba opcjonalne; None = bez zmiany).
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    instructions: Optional[str] = Field(None, max_length=20000)


@router.get("")
def list_projects(b: Backend = Depends(get_backend)) -> dict:
    # M22: czat/galeria/historia widzą TYLKO projekty czatu; workspace'y Code (kind='code')
    # są wykluczone (należą do modułu Code).
    return {
        "projects": [p.to_dict() for p in b.list_projects(kind="chat")],
        "recent_workspaces": b.recent_workspaces(),
        "current_project_id": b.current_project_id,
    }


@router.post("")
def create_project(req: CreateProjectReq, b: Backend = Depends(get_backend)) -> dict:
    proj = b.create_project(req.name, root=req.root or "")
    return {"project": proj.to_dict(), "current_project_id": b.current_project_id}


@router.patch("/{project_id}")
def update_project(project_id: str, req: UpdateProjectReq,
                   b: Backend = Depends(get_backend)) -> dict:
    """M22: zmień nazwę i/lub instrukcje projektu czatu."""
    proj = b.update_project(project_id, name=req.name, instructions=req.instructions)
    if proj is None:
        raise HTTPException(status_code=404, detail="Unknown project")
    return {"project": proj.to_dict()}


@router.delete("/{project_id}")
def delete_project(project_id: str, b: Backend = Depends(get_backend)) -> dict:
    """M22: usuń projekt + jego historię/artefakty/wiedzę. Czyści aktywny, jeśli dotyczył."""
    proj = b.delete_project(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Unknown project")
    return {"ok": True, "current_project_id": b.current_project_id}


@router.post("/current")
def select_project(req: SelectProjectReq, b: Backend = Depends(get_backend)) -> dict:
    try:
        b.select_project(req.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    cur = b.current_project()
    return {"current_project_id": b.current_project_id,
            "project": cur.to_dict() if cur else None}
