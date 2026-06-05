"""Trasy „wiedzy projektu" (M10-B5).

xAI nie wspiera serwerowych vector stores (`/v1/vector_stores` → 404), więc dokumenty
wiedzy projektu są trzymane **lokalnie** (`DATA_DIR/project_docs/<project_id>`) i
dołączane do wiadomości jako `input_file` na żądanie (przycisk „Attach all" w UI —
ścieżka B4, sprawdzona na realnym API). Bez kosztu per wiadomość: user decyduje, kiedy
dołączyć dokumenty.

- `POST   /collections/files`            — dodaj dokument (data-URI base64) do projektu.
- `GET    /collections`                  — lista dokumentów wiedzy aktywnego projektu.
- `GET    /collections/files/{id}/content` — treść dokumentu (do dołączenia w composerze).
- `DELETE /collections/files/{id}`       — usuń dokument (plik lokalny + rekord).

Wymaga aktywnego projektu (wiedza jest per projekt).
"""

from __future__ import annotations

import base64
import binascii
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator

from grok_core import validation as V
from grok_core.errors import upstream_error
from grok_core.state import Backend, get_backend

log = logging.getLogger(__name__)

router = APIRouter(tags=["collections"])


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


def _mime_of(data_uri: str) -> str:
    """Wyłuskaj MIME z `data:<mime>;base64,…` (puste, jeśli nietypowe)."""
    try:
        head = data_uri.split(",", 1)[0]  # data:<mime>;base64
        return head[len("data:"):].split(";", 1)[0]
    except Exception:
        return ""


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
        cf = b.collection_upload(raw, req.name, _mime_of(req.data))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise upstream_error(exc, "Could not save the document")
    return {"file": cf.to_dict()}


@router.get("/collections")
def list_collection(b: Backend = Depends(get_backend)) -> dict:
    files = b.collection_files()
    return {
        "files": [f.to_dict() for f in files],
        "project_id": b.current_project_id,
        "has_collection": bool(files),
    }


@router.get("/collections/files/{file_id}/content")
def get_collection_file_content(file_id: str, b: Backend = Depends(get_backend)):
    cf = b.collection_file_path(file_id)  # anty-traversal (pod PROJECT_DOCS_DIR)
    if cf is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return FileResponse(cf.path, media_type=cf.mime or "application/octet-stream",
                        filename=cf.name or "document")


@router.delete("/collections/files/{file_id}")
def delete_collection_file(file_id: str, b: Backend = Depends(get_backend)) -> dict:
    if not b.collection_remove(file_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return {"ok": True}
