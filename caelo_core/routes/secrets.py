"""Prywatny kanał sekretów między Electron main i sidecarem.

Nie używa publicznego tokenu REST widocznego rendererowi. Osobny token kanału
jest przekazywany do sidecara przez stdin i porównywany w stałym czasie.
"""

from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from caelo_core.runtime_secrets import SCHEMA_VERSION


router = APIRouter(prefix="/internal/secrets", tags=["internal"])


class SecretSnapshotPayload(BaseModel):
    version: int = Field(default=SCHEMA_VERSION)
    revision: int = Field(default=0, ge=0)
    xai_api_key: str = Field(default="", max_length=65536)
    google_api_key: str = Field(default="", max_length=65536)
    openai_api_key: str = Field(default="", max_length=65536)
    oauth_tokens: dict[str, Any] = Field(default_factory=dict)


def _authorize(request: Request, supplied: str | None) -> None:
    expected = str(getattr(request.app.state, "secret_channel_token", "") or "")
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=401, detail="Unauthorized secret channel")


@router.post("/import", include_in_schema=False)
def import_secrets(
    payload: SecretSnapshotPayload,
    request: Request,
    x_caelo_secret_token: str | None = Header(default=None),
) -> dict:
    _authorize(request, x_caelo_secret_token)
    backend = getattr(request.app.state, "backend", None)
    if backend is None:
        raise HTTPException(status_code=503, detail="Backend unavailable")
    snapshot = backend.import_secret_snapshot(payload.model_dump())
    return {"ok": True, "revision": snapshot["revision"]}


@router.get("/export", include_in_schema=False)
def export_secrets(
    request: Request,
    since: int = -1,
    x_caelo_secret_token: str | None = Header(default=None),
) -> dict:
    _authorize(request, x_caelo_secret_token)
    backend = getattr(request.app.state, "backend", None)
    if backend is None:
        raise HTTPException(status_code=503, detail="Backend unavailable")
    snapshot = backend.export_secret_snapshot()
    if int(snapshot["revision"]) <= since:
        return {"changed": False, "revision": snapshot["revision"]}
    return {"changed": True, "snapshot": snapshot, "revision": snapshot["revision"]}
