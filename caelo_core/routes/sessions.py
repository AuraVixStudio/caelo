"""Trasy REST sesji agenta kodowania (M21): lista / odczyt / kasowanie.

Sesje zapisuje `AgentRunner` (WS `/agent/stream`, po każdej turze) oraz tryb
headless (M19-B1) w `DATA_DIR/sessions/<id>.json`. Tu wystawiamy je dla UI:
- `GET /agent/sessions?project_id=` — lista metadanych (filtr po projekcie, M9-B5),
- `GET /agent/sessions/{id}`        — pełna sesja z historią (transkrypt + wznowienie),
- `DELETE /agent/sessions/{id}`     — usunięcie.

Magazyn (`agent/sessions.py`) czyta `DATA_DIR` sam (sesje są globalne na maszynie,
nie per-Backend), więc trasy nie potrzebują `Backend`. Fail-closed na tokenie
(router montowany pod `require_token` w server.py — jak pozostałe trasy REST).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from caelo_core.agent import sessions

router = APIRouter(prefix="/agent", tags=["sessions"])


@router.get("/sessions")
def list_sessions(project_id: Optional[str] = Query(default=None)) -> dict:
    """Metadane sesji (bez historii), najnowsze pierwsze. `project_id` filtruje
    po projekcie; brak parametru = wszystkie (też sesje bez projektu)."""
    return {"sessions": sessions.list_meta(project_id)}


@router.get("/sessions/{sid}")
def get_session(sid: str) -> dict:
    """Pełna sesja (z `history`) do rekonstrukcji transkryptu i wznowienia."""
    data = sessions.load(sid)
    if not data:
        raise HTTPException(status_code=404, detail="Session not found")
    return data


@router.delete("/sessions/{sid}")
def delete_session(sid: str) -> dict:
    if not sessions.delete(sid):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}
