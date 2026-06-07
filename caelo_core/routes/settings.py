"""Trasy ustawień aplikacji (klucz API, modele, system prompt, temperatura).

Klucz API jest zapisywany, ale NIGDY nie zwracany w całości (tylko flaga
`has_api_key`), by nie wyciekał do frontendu.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

import config  # type: ignore

from caelo_core import validation as V
from caelo_core.state import Backend, get_backend

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
    # M19-B9: domyślny reasoning_effort czatu / agenta (low|medium|high). Walidowane
    # w put_settings (śmieć → pominięte), by w pliku ustawień nie wylądowała zła wartość.
    chat_effort: Optional[str] = None
    code_effort: Optional[str] = None
    # M10-F3: domyślny tryb live-searcha czatu + wybrane źródła (per aplikacja).
    chat_search_mode: Optional[str] = None
    chat_search_sources: Optional[List[str]] = None
    # M12-F4: domyślny głos TTS/rozmowy + język (per aplikacja).
    voice: Optional[str] = None
    voice_language: Optional[str] = None


@router.get("/settings")
def get_settings(b: Backend = Depends(get_backend)) -> dict:
    s = b.read_settings()
    mode = s.get("chat_search_mode", "off")
    if mode not in _SEARCH_MODES:
        mode = "off"
    sources = [x for x in (s.get("chat_search_sources") or ["web", "x"]) if x in _SEARCH_SOURCES]
    voice = s.get("voice") or config.DEFAULT_VOICE
    if voice not in config.VOICE_VOICES:
        voice = config.DEFAULT_VOICE
    return {
        "chat_model": s.get("chat_model", config.DEFAULT_CHAT_MODEL),
        "code_model": s.get("code_model", "grok-build-0.1"),
        "system_prompt": s.get("system_prompt", ""),
        "chat_temperature": s.get("chat_temperature", 0.7),
        # M19-B9: domyślny effort (pusty string = brak / dziedzicz; UI pokazuje „Auto").
        "chat_effort": V.normalize_effort(s.get("chat_effort")) or "",
        "code_effort": V.normalize_effort(s.get("code_effort")) or "",
        "chat_search_mode": mode,
        "chat_search_sources": sources or ["web", "x"],
        # M12-F4: domyślny głos/język audio (TTS, read-aloud, Talk).
        "voice": voice,
        "voice_language": s.get("voice_language") or "en",
        "has_api_key": b.has_api_key(),
    }


@router.put("/settings")
def put_settings(patch: SettingsPatch, b: Backend = Depends(get_backend)) -> dict:
    data = patch.model_dump(exclude_none=True)
    # M19-B9: znormalizuj effort przed zapisem — śmieć/puste → "" (Auto/dziedzicz),
    # poprawne → low/medium/high. Nigdy nie zapisujemy nieprawidłowej wartości.
    for key in ("chat_effort", "code_effort"):
        if key in data:
            data[key] = V.normalize_effort(data[key]) or ""
    b.update_settings(data)
    return {"ok": True}
