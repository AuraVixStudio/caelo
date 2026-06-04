"""Trasy ustawień aplikacji (klucz API, modele, system prompt, temperatura).

Klucz API jest zapisywany, ale NIGDY nie zwracany w całości (tylko flaga
`has_api_key`), by nie wyciekał do frontendu.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

import config  # type: ignore

from grok_core.state import Backend, get_backend

router = APIRouter(tags=["settings"])


class SettingsPatch(BaseModel):
    api_key: Optional[str] = None
    chat_model: Optional[str] = None
    code_model: Optional[str] = None
    system_prompt: Optional[str] = None
    chat_temperature: Optional[float] = None


@router.get("/settings")
def get_settings(b: Backend = Depends(get_backend)) -> dict:
    s = b.read_settings()
    return {
        "chat_model": s.get("chat_model", config.DEFAULT_CHAT_MODEL),
        "code_model": s.get("code_model", "grok-build-0.1"),
        "system_prompt": s.get("system_prompt", ""),
        "chat_temperature": s.get("chat_temperature", 0.7),
        "has_api_key": b.has_api_key(),
    }


@router.put("/settings")
def put_settings(patch: SettingsPatch, b: Backend = Depends(get_backend)) -> dict:
    b.update_settings(patch.model_dump(exclude_none=True))
    return {"ok": True}
