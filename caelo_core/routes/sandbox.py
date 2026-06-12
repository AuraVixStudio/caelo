"""Trasa statusu sandboxa OS (S34-d).

Diagnostyka: jaki profil jest aktywny i czy OS-sandbox jest faktycznie dostępny na tej
platformie. Na Windows `wrap()` to cichy no-op — renderer pokazuje ostrzeżenie, by user
nie zakładał izolacji, której nie ma. Token egzekwowany przez `dependencies=guard`
przy `include_router` (jak pozostałe trasy).
"""
from __future__ import annotations

from fastapi import APIRouter

from caelo_core.sandbox import resolve_profile, sandbox_availability

router = APIRouter(tags=["sandbox"])


@router.get("/sandbox/status")
def sandbox_status() -> dict:
    return {"profile": resolve_profile().name, "availability": sandbox_availability()}
