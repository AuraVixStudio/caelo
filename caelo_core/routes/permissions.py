"""Trasy allowlisty agenta (panel Permissions).

Pozwalają przejrzeć reguły „Always allow" zapisane w `caelo_permissions.json`
i wyczyścić je jednym kliknięciem. Reguły dodaje sam agent, gdy użytkownik wybierze
„Always allow" na karcie zatwierdzania (WS /agent/stream).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from caelo_core.state import Backend, get_backend

router = APIRouter(prefix="/permissions", tags=["permissions"])


@router.get("")
def list_rules(b: Backend = Depends(get_backend)) -> dict:
    return {"rules": b.permissions.rules()}


@router.delete("")
def clear_rules(b: Backend = Depends(get_backend)) -> dict:
    b.permissions.clear()
    return {"ok": True, "rules": []}
