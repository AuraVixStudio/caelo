"""Trasy REST hooków cyklu życia narzędzi (M14-B5/F4).

Podejrzyj/włącz/edytuj hooki (pre/post-tool, pre-session) i przejrzyj log audytu.
Hooki są deterministyczne i niezależne od modelu — uogólnienie `PermissionGate`.
Fail-closed na tokenie (router montowany pod `require_token` w server.py).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from caelo_core.state import Backend, get_backend

router = APIRouter(prefix="/hooks", tags=["hooks"])


class HookReq(BaseModel):
    id: Optional[str] = None
    event: str                                   # pre_tool | post_tool | pre_session
    type: str                                    # block_command | block_path | audit | run_script
    enabled: bool = True
    description: Optional[str] = None
    pattern: Optional[str] = None                # block_*: regex
    command: Optional[list[str]] = None          # run_script: argv ({path} podstawiane)
    match_tools: list[str] = Field(default_factory=list)


class EnabledReq(BaseModel):
    enabled: bool


@router.get("")
def list_hooks(b: Backend = Depends(get_backend)) -> dict:
    return {"hooks": b.hooks.list_hooks()}


@router.post("")
def add_hook(req: HookReq, b: Backend = Depends(get_backend)) -> dict:
    try:
        return {"hook": b.hooks.add_hook(req.model_dump(exclude_none=False))}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/{hid}/enabled")
def set_enabled(hid: str, req: EnabledReq, b: Backend = Depends(get_backend)) -> dict:
    try:
        return {"hook": b.hooks.set_enabled(hid, req.enabled)}
    except ValueError:
        raise HTTPException(status_code=404, detail="Unknown hook")


@router.delete("/{hid}")
def remove_hook(hid: str, b: Backend = Depends(get_backend)) -> dict:
    if not b.hooks.remove_hook(hid):
        raise HTTPException(status_code=404, detail="Unknown hook")
    return {"ok": True}


@router.get("/audit")
def audit_log(limit: int = 200, b: Backend = Depends(get_backend)) -> dict:
    return {"entries": b.hooks.audit_tail(limit=max(1, min(limit, 2000)))}


@router.delete("/audit")
def clear_audit(b: Backend = Depends(get_backend)) -> dict:
    b.hooks.clear_audit()
    return {"ok": True}
