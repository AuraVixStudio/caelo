"""Trasy REST menedżera serwerów MCP (M14-B1/F1).

Dodaj/usuń/włącz serwer (stdio lub remote-xAI), wystartuj/zatrzymaj, podejrzyj
status i odkryte narzędzia. Start serwera stdio = uruchomienie dowolnej komendy →
osobny, jawny endpoint `start` (UI pyta o zgodę, jak run_command). Sekrety
(`authorization`, wartości `env`) NIE wracają do renderera (manager je maskuje).

Fail-closed na tokenie (router montowany pod `require_token` w server.py).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from caelo_core.state import Backend, get_backend

router = APIRouter(prefix="/mcp", tags=["mcp"])


class McpServerReq(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    transport: str = "stdio"               # "stdio" | "remote"
    command: Optional[list[str]] = None    # stdio: argv
    cwd: Optional[str] = None
    env: dict[str, str] = Field(default_factory=dict)
    url: Optional[str] = None              # remote: server_url
    authorization: Optional[str] = None    # remote: nagłówek auth
    server_label: Optional[str] = None
    enabled: bool = True


class EnabledReq(BaseModel):
    enabled: bool


@router.get("")
def list_servers(b: Backend = Depends(get_backend)) -> dict:
    return {"servers": b.mcp.all_status()}


@router.post("")
def add_server(req: McpServerReq, b: Backend = Depends(get_backend)) -> dict:
    try:
        cfg = b.mcp.add_server(req.model_dump(exclude_none=False))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"server": cfg}


@router.delete("/{sid}")
def remove_server(sid: str, b: Backend = Depends(get_backend)) -> dict:
    if not b.mcp.remove_server(sid):
        raise HTTPException(status_code=404, detail="Unknown server")
    return {"ok": True}


@router.put("/{sid}/enabled")
def set_enabled(sid: str, req: EnabledReq, b: Backend = Depends(get_backend)) -> dict:
    try:
        return {"server": b.mcp.set_enabled(sid, req.enabled)}
    except ValueError:
        raise HTTPException(status_code=404, detail="Unknown server")


@router.post("/{sid}/start")
def start_server(sid: str, b: Backend = Depends(get_backend)) -> dict:
    """Wystartuj serwer stdio (jawna zgoda usera w UI — uruchamia dowolną komendę)."""
    try:
        return {"server": b.mcp.start_server(sid)}
    except ValueError:
        raise HTTPException(status_code=404, detail="Unknown server")


@router.post("/{sid}/stop")
def stop_server(sid: str, b: Backend = Depends(get_backend)) -> dict:
    try:
        return {"server": b.mcp.stop_server(sid)}
    except ValueError:
        raise HTTPException(status_code=404, detail="Unknown server")


@router.get("/{sid}")
def server_status(sid: str, b: Backend = Depends(get_backend)) -> dict:
    try:
        return {"server": b.mcp.status(sid)}
    except ValueError:
        raise HTTPException(status_code=404, detail="Unknown server")
