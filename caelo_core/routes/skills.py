"""Trasy REST biblioteki skilli (M14-B6/F5).

Lista (wbudowane + użytkownika), podgląd treści, włącz/wyłącz (wstrzykiwane do
agenta), tworzenie z szablonu (Ren'Py/DAZ/blank), usuwanie (tylko użytkownika).
Fail-closed na tokenie.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from caelo_core.state import Backend, get_backend

router = APIRouter(prefix="/skills", tags=["skills"])


class CreateSkillReq(BaseModel):
    id: str
    template: str = "blank"      # blank | renpy | daz
    name: Optional[str] = None
    description: Optional[str] = None


class EnabledReq(BaseModel):
    enabled: bool


@router.get("")
def list_skills(b: Backend = Depends(get_backend)) -> dict:
    return {"skills": b.skills.list_skills()}


@router.post("")
def create_skill(req: CreateSkillReq, b: Backend = Depends(get_backend)) -> dict:
    try:
        return {"skill": b.skills.create_skill(req.id, template=req.template,
                                               name=req.name or "", description=req.description or "")}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{sid}")
def get_skill(sid: str, b: Backend = Depends(get_backend)) -> dict:
    sk = b.skills.get_skill(sid)
    if sk is None:
        raise HTTPException(status_code=404, detail="Unknown skill")
    return {"skill": sk}


@router.put("/{sid}/enabled")
def set_enabled(sid: str, req: EnabledReq, b: Backend = Depends(get_backend)) -> dict:
    try:
        return {"skill": b.skills.set_enabled(sid, req.enabled)}
    except ValueError:
        raise HTTPException(status_code=404, detail="Unknown skill")


@router.delete("/{sid}")
def delete_skill(sid: str, b: Backend = Depends(get_backend)) -> dict:
    if not b.skills.delete_skill(sid):
        raise HTTPException(status_code=400, detail="Cannot delete (unknown or built-in skill)")
    return {"ok": True}
