"""Trasy REST komend slash (M14-B4/F3).

Lista wbudowanych + użytkownika; dodawanie/usuwanie komend użytkownika. Wykonanie
(wstawienie szablonu, tryb, akcja) robi renderer. Fail-closed na tokenie.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from grok_core.state import Backend, get_backend

router = APIRouter(prefix="/commands", tags=["commands"])


class CommandReq(BaseModel):
    name: str
    template: str
    description: Optional[str] = None
    target: str = "both"          # chat | agent | both
    mode: Optional[str] = None    # opcjonalny tryb agenta
    action: Optional[str] = None  # opcjonalna akcja klienta


@router.get("")
def list_commands(b: Backend = Depends(get_backend)) -> dict:
    return {"commands": b.commands.list_commands()}


@router.post("")
def add_command(req: CommandReq, b: Backend = Depends(get_backend)) -> dict:
    try:
        return {"command": b.commands.add_command(req.model_dump(exclude_none=False))}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/{name}")
def remove_command(name: str, b: Backend = Depends(get_backend)) -> dict:
    if not b.commands.remove_command(name):
        raise HTTPException(status_code=404, detail="Unknown or built-in command")
    return {"ok": True}
