"""Trasy ustawień aplikacji.

Sekrety są przyjmowane dla zgodności klienta, ale trafiają wyłącznie do pamięci
sidecara. Proces główny Electron przechwytuje je i utrwala przez ``safeStorage``.
Pełna wartość nigdy nie jest zwracana do renderera.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

import config  # type: ignore

from caelo_core import validation as V
from caelo_core.providers.ids import ACTIVE_AGENT_PROVIDER_IDS, ACTIVE_CHAT_PROVIDER_IDS
from caelo_core.state import Backend, get_backend

router = APIRouter(tags=["settings"])

# M10-F3: dozwolone tryby live-searcha (auto/on/off) + źródła (web/x/news).
_SEARCH_MODES = {"auto", "on", "off"}
_SEARCH_SOURCES = {"web", "x", "news"}


# Preferencja zrodla uwierzytelniania ("przelacznik trybow"): auto|oauth|api_key.
_AUTH_SOURCES = {"auto", "oauth", "api_key"}


class SettingsPatch(BaseModel):
    api_key: Optional[str] = None
    # Preferowane zrodlo klucza dla wywolan xAI (auto = OAuth->klucz->.env).
    auth_source: Optional[str] = None
    chat_model: Optional[str] = None
    # Dostawca, do ktorego nalezy `chat_model` — domyslny model czatu moze byc
    # z dowolnego providera, wiec sama nazwa modelu juz nie wystarcza (jak w kodzie).
    chat_provider: Optional[str] = None
    code_model: Optional[str] = None
    code_provider: Optional[str] = None
    system_prompt: Optional[str] = None
    chat_temperature: Optional[float] = None
    # M19-B9: domyślny reasoning_effort czatu / agenta (low|medium|high|xhigh). Walidowane
    # w put_settings (śmieć → pominięte), by w pliku ustawień nie wylądowała zła wartość.
    chat_effort: Optional[str] = None
    code_effort: Optional[str] = None
    # M10-F3: domyślny tryb live-searcha czatu + wybrane źródła (per aplikacja).
    chat_search_mode: Optional[str] = None
    chat_search_sources: Optional[List[str]] = None
    # M12-F4: domyślny głos TTS/rozmowy + język (per aplikacja).
    voice: Optional[str] = None
    voice_language: Optional[str] = None
    # Google: ADC/Vertex jako tryb glowny, klucz AI Studio jako alternatywa.
    google_auth_mode: Optional[str] = None
    google_project_id: Optional[str] = None
    google_location: Optional[str] = None
    google_video_location: Optional[str] = None
    google_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None


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
        "chat_provider": s.get("chat_provider", "xai"),
        "code_model": s.get("code_model", "grok-build-0.1"),
        "code_provider": s.get("code_provider", "xai"),
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
        "google_auth_mode": s.get("google_auth_mode") or "vertex",
        "google_project_id": s.get("google_project_id") or "",
        "google_location": s.get("google_location") or "global",
        "google_video_location": s.get("google_video_location") or "us-central1",
        "google_has_api_key": (
            b.has_google_api_key()
            if hasattr(b, "has_google_api_key")
            else bool((s.get("google_api_key") or "").strip())
        ),
        "openai_has_api_key": (
            b.has_openai_api_key() if hasattr(b, "has_openai_api_key") else False
        ),
        "openai_auth_source": (
            b.openai_auth_source() if hasattr(b, "openai_auth_source") else "none"
        ),
    }


@router.put("/settings")
def put_settings(patch: SettingsPatch, b: Backend = Depends(get_backend)) -> dict:
    data = patch.model_dump(exclude_none=True)
    # ADR-5: usuń sekrety PRZED sanitize/update_settings, aby nawet bez Electrona
    # bezpośrednie żądanie REST nie mogło zapisać ich do caelo_settings.json.
    xai_api_key = data.pop("api_key", None)
    google_api_key = data.pop("google_api_key", None)
    openai_api_key = data.pop("openai_api_key", None)
    from caelo_core.providers.google.config import sanitize_settings_patch

    data = sanitize_settings_patch(data)
    # M19-B9: znormalizuj effort przed zapisem — śmieć/puste → "" (Auto/dziedzicz),
    # poprawne → low/medium/high. Nigdy nie zapisujemy nieprawidłowej wartości.
    for key in ("chat_effort", "code_effort"):
        if key in data:
            data[key] = V.normalize_effort(data[key]) or ""
    # Preferencja zrodla auth — niepoprawna wartosc pomijana (nie psujemy pliku ustawien).
    if "auth_source" in data and data["auth_source"] not in _AUTH_SOURCES:
        data.pop("auth_source")
    if "code_provider" in data and data["code_provider"] not in ACTIVE_AGENT_PROVIDER_IDS:
        data.pop("code_provider")
    if "chat_provider" in data and data["chat_provider"] not in ACTIVE_CHAT_PROVIDER_IDS:
        data.pop("chat_provider")
    b.update_settings(data)
    if xai_api_key is not None:
        b.set_api_key(str(xai_api_key))
    if google_api_key is not None:
        b.set_google_api_key(str(google_api_key))
    if openai_api_key is not None:
        b.set_openai_api_key(str(openai_api_key))
    return {"ok": True}


@router.delete("/settings/api-key")
def delete_api_key(b: Backend = Depends(get_backend)) -> dict:
    """Usun zapisany klucz API (nie dotyka XAI_API_KEY z .env ani logowania OAuth)."""
    b.clear_api_key()
    return {"ok": True}


@router.delete("/settings/google-api-key")
def delete_google_api_key(b: Backend = Depends(get_backend)) -> dict:
    """Usun tylko zapisany klucz AI Studio; nie dotykaj ADC ani gcloud."""
    b.clear_google_api_key()
    return {"ok": True}


@router.delete("/settings/openai-api-key")
def delete_openai_api_key(b: Backend = Depends(get_backend)) -> dict:
    """Usuń klucz OpenAI z sejfu; nie dotykaj OPENAI_API_KEY ze środowiska."""
    b.clear_openai_api_key()
    return {"ok": True}
