"""Trasy systemowe: historia generacji i folder wyjściowy (HistoryManager)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from caelo_core.state import Backend, get_backend

router = APIRouter(tags=["system"])


@router.get("/history/generations")
def get_history(b: Backend = Depends(get_backend)) -> dict:
    """Legacy historia generacji mediów (HistoryManager) — {timestamp, mode, prompt, url}.

    M9-B3: ścieżka przeniesiona z `/history` na `/history/generations`, bo kanoniczne
    `/history` przejął kręgosłup huba (caelo_core.routes.history — zdarzenia wszystkich
    trybów). Ta trasa zostaje dla obecnej zakładki History do czasu jej przebudowy (M9-F3)."""
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
