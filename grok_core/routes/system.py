"""Trasy systemowe: historia generacji i folder wyjściowy (HistoryManager)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from grok_core.state import Backend, get_backend

router = APIRouter(tags=["system"])


@router.get("/history")
def get_history(b: Backend = Depends(get_backend)) -> dict:
    """Wpisy historii generacji (najnowsze pierwsze) — {timestamp, mode, prompt, url}."""
    return {"entries": list(b.history.get_entries())}


class OutputDir(BaseModel):
    path: str


@router.get("/config/output-dir")
def get_output_dir(b: Backend = Depends(get_backend)) -> dict:
    return {"path": b.history.get_save_path()}


@router.put("/config/output-dir")
def set_output_dir(body: OutputDir, b: Backend = Depends(get_backend)) -> dict:
    b.history.set_save_path(body.path)
    return {"ok": True, "path": b.history.get_save_path()}
