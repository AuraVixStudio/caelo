"""Trasy serwerów LSP (M19-B3) — konfiguracja w panelu Extensions → Language Servers.

GET listę (+ status), POST dodaj/aktualizuj, DELETE usuń, POST /{name}/restart. Konfig
GLOBALNY trzymany w `DATA_DIR/lsp.json` (atomowy zapis); projektowy (`<ws>/.caelo/lsp.json`)
jest tylko czytany przy starcie. Po zmianie configu menedżer jest przebudowywany.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import config  # type: ignore

from caelo_core.state import Backend, get_backend

router = APIRouter(prefix="/lsp", tags=["lsp"])


def _lsp_file():
    return config.DATA_DIR / "lsp.json"


def _load() -> dict:
    d = config.load_json_or_backup(_lsp_file(), {}) or {}
    return d if isinstance(d, dict) else {}


def _save(d: dict) -> None:
    config.atomic_write_text(_lsp_file(), json.dumps(d, indent=2, ensure_ascii=False))


def _from_config(cfgs: dict) -> list:
    return [{"name": n, "command": c.get("command"), "args": c.get("args") or [],
             "languages": sorted(set((c.get("extensionToLanguage") or {}).values())),
             "running": False} for n, c in cfgs.items()]


class LspServerBody(BaseModel):
    name: str
    command: str
    args: list[str] = Field(default_factory=list)
    extensionToLanguage: dict = Field(default_factory=dict)
    env: dict = Field(default_factory=dict)
    startupTimeout: int = 30000
    restartOnCrash: bool = True
    maxRestarts: int = 3


@router.get("")
def list_servers(b: Backend = Depends(get_backend)) -> dict:
    mgr = b.get_lsp()
    if mgr is not None:
        return {"servers": mgr.list_servers(), "has_workspace": True}
    return {"servers": _from_config(_load()), "has_workspace": False}


@router.post("")
def add_server(body: LspServerBody, b: Backend = Depends(get_backend)) -> dict:
    if not body.name.strip() or not body.command.strip():
        raise HTTPException(status_code=400, detail="name and command are required")
    if not body.extensionToLanguage:
        raise HTTPException(status_code=400, detail="extensionToLanguage is required")
    d = _load()
    d[body.name] = {
        "command": body.command, "args": body.args,
        "extensionToLanguage": body.extensionToLanguage, "env": body.env,
        "startupTimeout": body.startupTimeout, "restartOnCrash": body.restartOnCrash,
        "maxRestarts": body.maxRestarts,
    }
    _save(d)
    b.reload_lsp()  # przebuduj menedżera z nowym configiem
    return {"ok": True}


@router.delete("/{name}")
def remove_server(name: str, b: Backend = Depends(get_backend)) -> dict:
    d = _load()
    if name in d:
        del d[name]
        _save(d)
        b.reload_lsp()
    return {"ok": True}


@router.post("/{name}/restart")
def restart_server(name: str, b: Backend = Depends(get_backend)) -> dict:
    mgr = b.get_lsp()
    if mgr is None:
        raise HTTPException(status_code=400, detail="no workspace selected")
    return {"ok": mgr.restart(name)}
