"""Trasy REST zespołu subagentów (M17-B4/B6, F2/F4/F5).

Spójne z WS `/agent/stream` (subagenci rejestrują scalenia w tym samym magazynie
Backendu — jeden mechanizm, jak checkpointy/allowlista). Fail-closed na tokenie
(router montowany pod `require_token`).

- role + limity (F4): definicja/edycja ról i limitów zespołu,
- scalenia (F2): lista oczekujących merge'ów worktree, diff, accept/reject, konflikty,
- przebiegi (F5): ostatnie raporty kosztu/telemetrii zespołu.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from caelo_core.state import Backend, get_backend

router = APIRouter(prefix="/agent/team", tags=["team"])


# --- role + limity (F4) ---------------------------------------------------------
@router.get("/roles")
def list_roles(b: Backend = Depends(get_backend)) -> dict:
    reg = b.subagents
    return {"roles": reg.list(), "limits": reg.limits()}


class RoleReq(BaseModel):
    id: str
    label: Optional[str] = None
    description: Optional[str] = None
    tools: Optional[list[str]] = None
    mcp: Optional[str] = None
    worktree: Optional[bool] = None
    model: Optional[str] = None
    prompt: Optional[str] = None


@router.post("/roles")
def upsert_role(req: RoleReq, b: Backend = Depends(get_backend)) -> dict:
    try:
        role = b.subagents.upsert_role(req.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"role": role}


@router.delete("/roles/{role_id}")
def remove_role(role_id: str, b: Backend = Depends(get_backend)) -> dict:
    """Usuń rolę/nadpisanie usera (wbudowana wraca do domyślnej)."""
    removed = b.subagents.remove_role(role_id)
    return {"ok": removed, "roles": b.subagents.list()}


class LimitsReq(BaseModel):
    max_parallel: Optional[int] = None
    max_depth: Optional[int] = None
    timeout_s: Optional[int] = None
    max_subagents: Optional[int] = None
    max_total_turns: Optional[int] = None
    max_iters: Optional[int] = None


@router.put("/limits")
def set_limits(req: LimitsReq, b: Backend = Depends(get_backend)) -> dict:
    return {"limits": b.subagents.set_limits(req.model_dump(exclude_none=True))}


# --- scalenia worktree (F2) -----------------------------------------------------
@router.get("/merges")
def list_merges(b: Backend = Depends(get_backend)) -> dict:
    store = b.get_team_merges()
    if store is None:
        return {"merges": [], "has_workspace": False}
    return {"merges": store.list(), "has_workspace": True}


@router.get("/merges/{merge_id}/diff")
def merge_diff(merge_id: str, b: Backend = Depends(get_backend)) -> dict:
    store = b.get_team_merges()
    diff = store.diff(merge_id) if store else None
    if diff is None:
        raise HTTPException(status_code=404, detail="Unknown merge")
    return {"diff": diff}


@router.post("/merges/{merge_id}/apply")
def apply_merge(merge_id: str, b: Backend = Depends(get_backend)) -> dict:
    store = b.get_team_merges()
    ws = b.get_workspace()
    if store is None or ws is None:
        raise HTTPException(status_code=400, detail="No workspace selected")
    try:
        # scalenie snapshotuje oryginał do checkpointu → cofalne przez M13 undo
        return store.apply(merge_id, ws, checkpoints=b.get_checkpoints())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/merges/{merge_id}/reject")
def reject_merge(merge_id: str, b: Backend = Depends(get_backend)) -> dict:
    store = b.get_team_merges()
    if store is None:
        raise HTTPException(status_code=400, detail="No workspace selected")
    try:
        return store.reject(merge_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/merges")
def clear_merges(b: Backend = Depends(get_backend)) -> dict:
    store = b.get_team_merges()
    if store is None:
        return {"ok": True, "cleared": 0}
    return store.clear()


# --- przebiegi / koszt (F5) -----------------------------------------------------
@router.get("/runs")
def list_runs(b: Backend = Depends(get_backend)) -> dict:
    return {"runs": b.team_reports()}
