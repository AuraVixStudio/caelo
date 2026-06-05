"""Trasy kolekcji projektu (M10-B5: trwała wiedza / file_search).

Dokumenty wgrane do kolekcji AKTYWNEGO projektu (vector store xAI) są przeszukiwane
narzędziem `file_search` w wielu rozmowach tego projektu (patrz `/chat/stream`).

- `POST /collections/files` — dodaj dokument (data-URI base64, jak media/voice) do
  kolekcji aktywnego projektu.
- `GET  /collections`       — lista dokumentów kolekcji aktywnego projektu.
- `DELETE /collections/files/{id}` — usuń dokument z kolekcji (xAI + rekord).

Upload idzie jako **data-URI w JSON** (spójnie z resztą tras — żadnej nowej zależności
`python-multipart`), walidowany przez `validation.validate_document_uri`. Wymaga aktywnego
projektu (kolekcje są per projekt). Surowe błędy xAI nie wyciekają (`errors.upstream_error`).
Realne endpointy vector store weryfikuje użytkownik (TLS w sandboxie) — to *stretch* M10.
"""

from __future__ import annotations

import base64
import binascii
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from grok_core import validation as V
from grok_core.collections_client import CollectionUpstreamError
from grok_core.errors import upstream_error
from grok_core.state import Backend, get_backend

log = logging.getLogger(__name__)

router = APIRouter(tags=["collections"])


def _hint_for_status(status: int) -> str:
    """Krótka, pomocna wskazówka dla użytkownika na podstawie statusu xAI."""
    if status == 404:
        return ("xAI returned 404 — this key/endpoint may not support file collections "
                "(vector stores / file_search).")
    if status in (401, 403):
        return "xAI rejected the request (auth). Server-side tools may require an API key, not OAuth."
    if status in (400, 422):
        return "xAI rejected the upload (bad request) — the vector-store API shape may differ."
    return f"xAI rejected the upload (HTTP {status})."


class UploadDocReq(BaseModel):
    name: str
    data: str  # data:<mime>;base64,<...>

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("name is required")
        return v[:255]

    @field_validator("data")
    @classmethod
    def _data(cls, v: str) -> str:
        return V.validate_document_uri(v)


@router.post("/collections/files")
def upload_collection_file(req: UploadDocReq, b: Backend = Depends(get_backend)) -> dict:
    if not b.current_project_id:
        raise HTTPException(status_code=400,
                            detail="Select or create a project before adding documents")
    try:
        raw = base64.b64decode(req.data.split(",", 1)[1])
    except (binascii.Error, IndexError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid base64 document")
    if len(raw) > V.MAX_COLLECTION_FILE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (> {V.MAX_COLLECTION_FILE_BYTES // (1024 * 1024)} MB)")
    try:
        cf = b.collection_upload(raw, req.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except CollectionUpstreamError as exc:
        # Surowe body tylko do logu (diagnostyka), do UI status + krótka wskazówka.
        log.error("Collection upload failed: %s :: %s", exc, exc.body)
        raise HTTPException(status_code=502, detail=_hint_for_status(exc.status))
    except Exception as exc:  # noqa: BLE001
        raise upstream_error(exc, "Could not add the document to the project collection")
    return {"file": cf.to_dict()}


@router.get("/collections")
def list_collection(b: Backend = Depends(get_backend)) -> dict:
    files = b.collection_files()
    return {
        "files": [f.to_dict() for f in files],
        "project_id": b.current_project_id,
        "has_collection": b.current_vector_store_id() is not None,
    }


@router.delete("/collections/files/{file_id}")
def delete_collection_file(file_id: str, b: Backend = Depends(get_backend)) -> dict:
    try:
        ok = b.collection_remove(file_id)
    except Exception as exc:  # noqa: BLE001
        raise upstream_error(exc, "Could not remove the document")
    if not ok:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"ok": True}
