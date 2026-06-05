"""Trasa listy modeli (czat + wideo) z fallbackiem na listę z config."""

from __future__ import annotations

from fastapi import APIRouter, Depends

import config  # type: ignore

from caelo_core.state import Backend, get_backend

router = APIRouter(tags=["models"])


@router.get("/models")
def list_models(b: Backend = Depends(get_backend)) -> dict:
    settings = b.read_settings()
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
    }
