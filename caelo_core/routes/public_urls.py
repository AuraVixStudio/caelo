"""Publiczne linki do artefaktów przez xAI Files API (docs.x.ai „Public URLs").

  POST   /artifacts/{id}/public-url   — wyślij plik do Files API (raz) i utwórz/odśwież link
  DELETE /artifacts/{id}/public-url   — unieważnij link (plik w Files API zostaje)

To jedyna trasa, która WYSYŁA lokalne medium do xAI bez generacji — dlatego wymaga
jawnego `confirm: true` (renderer pokazuje wcześniej kartę zgody: link jest publiczny,
każdy z linkiem zobaczy plik). `file_id` i link są pamiętane w `meta` artefaktu
(`xai_file_id`, `public_url`, `public_url_expires_at`), więc ponowne udostępnienie nie
wysyła pliku drugi raz, a odwołanie wie, co odwołać. Plik czytamy tylko z dozwolonych
katalogów mediów (ten sam sandbox co `/artifacts/{id}/content`).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from caelo_core.errors import upstream_error
from caelo_core.providers.xai.files import (
    PUBLIC_URL_MAX_BYTES,
    PUBLIC_URL_MAX_EXPIRY_S,
    PUBLIC_URL_MIME_TYPES,
    PUBLIC_URL_MIN_EXPIRY_S,
    XAIFilesClient,
)
from caelo_core.routes.history import _media_bases, _within
from caelo_core.state import Backend, get_backend

router = APIRouter(tags=["public-urls"])


class PublicUrlReq(BaseModel):
    # Zgoda użytkownika na upublicznienie pliku — bez niej nic nie wychodzi z maszyny.
    confirm: bool = False
    # None = link bez własnego wygaśnięcia (do odwołania / usunięcia pliku).
    expires_after: Optional[int] = Field(None, ge=PUBLIC_URL_MIN_EXPIRY_S,
                                         le=PUBLIC_URL_MAX_EXPIRY_S)


def _files(b: Backend) -> XAIFilesClient:
    return XAIFilesClient(b.get_api_key)


def _artifact_file(b: Backend, art) -> Path:
    if not art.path:
        raise HTTPException(status_code=404, detail="Artifact has no local file")
    try:
        target = Path(art.path).resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="Bad artifact path")
    if not any(_within(target, base) for base in _media_bases(b)):
        raise HTTPException(status_code=403, detail="Artifact path not allowed")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return target


def _state(meta: dict) -> dict:
    return {"public_url": meta.get("public_url"),
            "expires_at": meta.get("public_url_expires_at"),
            "file_id": meta.get("xai_file_id")}


@router.post("/artifacts/{artifact_id}/public-url")
def create_public_url(artifact_id: str, body: PublicUrlReq,
                      b: Backend = Depends(get_backend)) -> dict:
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Sharing requires explicit confirmation")
    art = b.history_store.get_artifact(artifact_id)
    if art is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    mime = (art.mime or "").lower()
    if mime not in PUBLIC_URL_MIME_TYPES:
        raise HTTPException(status_code=415, detail="This file type cannot get a public link")
    target = _artifact_file(b, art)
    if target.stat().st_size > PUBLIC_URL_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Files over 50 MiB cannot get a public link")
    client = _files(b)
    file_id = (art.meta or {}).get("xai_file_id")
    try:
        if not file_id:
            file_id = client.upload(target, mime)
            # Utrwal od razu: gdyby tworzenie linku padło, kolejna próba nie wyśle pliku drugi raz.
            b.history_store.update_artifact_meta(artifact_id, {"xai_file_id": file_id})
        try:
            result = client.create_public_url(file_id, body.expires_after)
        except FileNotFoundError:
            # Plik zniknął z Files API (usunięty/wygasł) — wyślij go jeszcze raz.
            file_id = client.upload(target, mime)
            b.history_store.update_artifact_meta(artifact_id, {"xai_file_id": file_id})
            result = client.create_public_url(file_id, body.expires_after)
    except PermissionError:
        raise HTTPException(status_code=401, detail="Sign in to xAI to share files")
    except Exception as exc:  # noqa: BLE001
        raise upstream_error(exc, "Could not create a public link")
    meta = b.history_store.update_artifact_meta(artifact_id, {
        "public_url": result["public_url"],
        "public_url_expires_at": result.get("expires_at"),
        "public_url_created_at": time.time(),
    }) or {}
    return _state(meta)


@router.delete("/artifacts/{artifact_id}/public-url")
def revoke_public_url(artifact_id: str, b: Backend = Depends(get_backend)) -> dict:
    art = b.history_store.get_artifact(artifact_id)
    if art is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    file_id = (art.meta or {}).get("xai_file_id")
    revoked = False
    if file_id:
        try:
            revoked = _files(b).revoke_public_url(file_id)
        except PermissionError:
            raise HTTPException(status_code=401, detail="Sign in to xAI to manage shared files")
        except FileNotFoundError:
            revoked = False  # plik już nie istnieje w Files API → link i tak nie działa
        except Exception as exc:  # noqa: BLE001
            raise upstream_error(exc, "Could not revoke the public link")
    meta = b.history_store.update_artifact_meta(artifact_id, {
        "public_url": None, "public_url_expires_at": None, "public_url_created_at": None,
    }) or {}
    return {**_state(meta), "revoked": revoked}
