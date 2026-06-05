"""Trasy ustawień aplikacji (klucz API, modele, system prompt, temperatura).

Klucz API jest zapisywany, ale NIGDY nie zwracany w całości (tylko flaga
`has_api_key`), by nie wyciekał do frontendu.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

import config  # type: ignore

from grok_core.state import Backend, get_backend

router = APIRouter(tags=["settings"])

# M10-F3: dozwolone tryby live-searcha (auto/on/off) + źródła (web/x/news).
_SEARCH_MODES = {"auto", "on", "off"}
_SEARCH_SOURCES = {"web", "x", "news"}


class SettingsPatch(BaseModel):
    api_key: Optional[str] = None
    chat_model: Optional[str] = None
    code_model: Optional[str] = None
    system_prompt: Optional[str] = None
    chat_temperature: Optional[float] = None
    # M10-F3: domyślny tryb live-searcha czatu + wybrane źródła (per aplikacja).
    chat_search_mode: Optional[str] = None
    chat_search_sources: Optional[List[str]] = None


@router.get("/settings")
def get_settings(b: Backend = Depends(get_backend)) -> dict:
    s = b.read_settings()
    mode = s.get("chat_search_mode", "off")
    if mode not in _SEARCH_MODES:
        mode = "off"
    sources = [x for x in (s.get("chat_search_sources") or ["web", "x"]) if x in _SEARCH_SOURCES]
    return {
        "chat_model": s.get("chat_model", config.DEFAULT_CHAT_MODEL),
        "code_model": s.get("code_model", "grok-build-0.1"),
        "system_prompt": s.get("system_prompt", ""),
        "chat_temperature": s.get("chat_temperature", 0.7),
        "chat_search_mode": mode,
        "chat_search_sources": sources or ["web", "x"],
        "has_api_key": b.has_api_key(),
    }


@router.put("/settings")
def put_settings(patch: SettingsPatch, b: Backend = Depends(get_backend)) -> dict:
    b.update_settings(patch.model_dump(exclude_none=True))
    return {"ok": True}
