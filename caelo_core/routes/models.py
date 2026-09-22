"""Katalog dostawcow, modeli i mozliwosci z zachowaniem starego `/models`."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

import config  # type: ignore

from caelo_core.state import Backend, get_backend
from caelo_core.models.registry import get_model_registry

router = APIRouter(tags=["models"])


@router.get("/models")
def list_models(
    provider: Optional[str] = Query(None, max_length=32),
    media_type: Optional[str] = Query(None, pattern="^(chat|image|video)$"),
    b: Backend = Depends(get_backend),
) -> dict:
    settings = b.read_settings()
    registry = get_model_registry()
    return {
        "chat": b.list_chat_models(),
        "image": list(config.IMAGE_MODELS),
        "video": list(config.VIDEO_MODELS),
        "voices": list(config.VOICE_VOICES),
        "default_chat": settings.get("chat_model") or config.DEFAULT_CHAT_MODEL,
        "default_image": config.DEFAULT_IMAGE_MODEL,
        "default_video": config.DEFAULT_VIDEO_MODEL,
        "default_voice": config.DEFAULT_VOICE,
        "realtime_model": config.VOICE_REALTIME_MODEL,
        # Domyślny model agenta kodowania (potwierdzony: grok-build-0.1).
        "default_code": settings.get("code_model") or "grok-build-0.1",
        # Nowy neutralny katalog. Stare pola wyzej pozostaja bez zmian, wiec
        # dotychczasowy renderer moze ignorowac rozszerzenie odpowiedzi.
        "items": [m.to_dict() for m in registry.models(
            provider=provider, media_type=media_type
        )],
    }


@router.get("/providers")
def list_providers() -> dict:
    registry = get_model_registry()
    return {
        "default": "xai",
        "providers": [p.to_dict() for p in registry.providers()],
    }


@router.post("/providers/{provider_id}/validate")
def validate_provider(provider_id: str, b: Backend = Depends(get_backend)) -> dict:
    """Lekki test konfiguracji bez uruchamiania platnej generacji."""
    if get_model_registry().provider(provider_id) is None:
        raise HTTPException(status_code=404, detail="Unknown provider")
    try:
        return b.get_provider(provider_id).validate_connection()
    except Exception as exc:
        from caelo_core.errors import upstream_error
        raise upstream_error(exc, "Provider connection test failed")


@router.get("/capabilities")
def list_capabilities(
    provider: Optional[str] = Query(None, max_length=32),
    model: Optional[str] = Query(None, max_length=128),
    media_type: Optional[str] = Query(None, pattern="^(chat|image|video)$"),
) -> dict:
    registry = get_model_registry()
    if provider and registry.provider(provider) is None:
        raise HTTPException(status_code=404, detail="Unknown provider")
    if model:
        provider_id = provider or "xai"
        found = registry.find(provider_id, model)
        if found is None:
            raise HTTPException(status_code=404, detail="Unknown model")
        if media_type and found.media_type != media_type:
            raise HTTPException(status_code=404, detail="Unknown model")
        return {"capability": found.to_dict()}
    return {
        "capabilities": [m.to_dict() for m in registry.models(
            provider=provider, media_type=media_type
        )]
    }
