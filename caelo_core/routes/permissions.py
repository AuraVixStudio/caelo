"""Trasy allowlisty agenta (panel Permissions).

Pozwalają przejrzeć reguły „Always allow" zapisane w `caelo_permissions.json`
i wyczyścić je jednym kliknięciem. Reguły dodaje sam agent, gdy użytkownik wybierze
„Always allow" na karcie zatwierdzania (WS /agent/stream).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from caelo_core.agent.permission_rules import parse_rule
from caelo_core.state import Backend, get_backend

router = APIRouter(prefix="/permissions", tags=["permissions"])

MAX_RULES = 200  # miękki limit (ochrona przed zalaniem) — backend lokalny, niskie ryzyko


@router.get("")
def list_rules(b: Backend = Depends(get_backend)) -> dict:
    return {"rules": b.permissions.rules()}


@router.delete("")
def clear_rules(b: Backend = Depends(get_backend)) -> dict:
    b.permissions.clear()
    return {"ok": True, "rules": []}


# --- reguły glob (M19-B4): allow/deny ToolPrefix(glob), deny>allow ---
class RulesBody(BaseModel):
    allow: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)


@router.get("/rules")
def get_glob_rules(b: Backend = Depends(get_backend)) -> dict:
    """Aktualne reguły glob (globalne + projektowe scalone w bramce)."""
    return b.permissions.rule_strings()


@router.put("/rules")
def put_glob_rules(body: RulesBody, b: Backend = Depends(get_backend)) -> dict:
    """Zapisz GLOBALNE reguły glob (caelo_settings.json) i przebuduj bramkę. Każdy wpis
    musi być poprawnym `ToolPrefix(glob)` — inaczej 400 (fail-closed: nic nie zapisujemy)."""
    if len(body.allow) > MAX_RULES or len(body.deny) > MAX_RULES:
        raise HTTPException(status_code=400, detail="Too many rules")
    for spec in (*body.allow, *body.deny):
        if parse_rule(spec) is None:
            raise HTTPException(status_code=400, detail=f"Invalid rule: {spec!r}")
    s = b.read_settings()
    s["permission_rules"] = {"allow": list(body.allow), "deny": list(body.deny)}
    b.write_settings(s)
    b.reload_permission_rules()  # scal z projektowymi i wstrzyknij do bramki
    return b.permissions.rule_strings()
