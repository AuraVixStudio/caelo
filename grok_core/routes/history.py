"""Trasy historii i artefaktów huba (M9-B3) — REST do czytania kręgosłupa.

  GET /history                — lista zdarzeń + filtry (q FTS / mode / project_id / from / to) + paginacja
  GET /artifacts              — lista artefaktów (te same filtry)
  GET /artifacts/{id}         — metadane artefaktu
  GET /artifacts/{id}/content — strumień pliku artefaktu (inline)

Magazyn: `grok_core.history_store` (SQLite/FTS5) przez `Backend.history_store`.
Wszystkie trasy są pod globalnym guardem tokenu w `server.py` (P1-10, fail-closed).
Limity wejścia z `validation.py` (naruszenie → 422). Treść artefaktu jest serwowana
tylko z dozwolonych katalogów (DATA_DIR / folder zapisu mediów) — plik poza nimi
jest ODMAWIANY (defense-in-depth: artefakt z podejrzaną ścieżką nie wyciąga
dowolnego pliku z dysku).
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

import config  # type: ignore

from grok_core import validation as V
from grok_core.history_store import Artifact
from grok_core.state import Backend, get_backend

router = APIRouter(tags=["history"])


@router.get("/history")
def list_history(
    b: Backend = Depends(get_backend),
    q: Optional[str] = Query(None, max_length=V.MAX_HISTORY_QUERY),
    mode: Optional[str] = Query(None, max_length=V.MAX_ID_LEN),
    project_id: Optional[str] = Query(None, max_length=V.MAX_ID_LEN),
    from_: Optional[float] = Query(None, alias="from"),
    to: Optional[float] = Query(None),
    limit: int = Query(50, ge=1, le=V.MAX_HISTORY_LIMIT),
    offset: int = Query(0, ge=0),
) -> dict:
    events = b.history_store.list_events(
        q=q, mode=mode, project_id=project_id, since=from_, until=to,
        limit=limit, offset=offset,
    )
    return {"events": [e.to_dict() for e in events],
            "limit": limit, "offset": offset, "count": len(events)}


@router.get("/artifacts")
def list_artifacts(
    b: Backend = Depends(get_backend),
    mode: Optional[str] = Query(None, max_length=V.MAX_ID_LEN),
    project_id: Optional[str] = Query(None, max_length=V.MAX_ID_LEN),
    from_: Optional[float] = Query(None, alias="from"),
    to: Optional[float] = Query(None),
    limit: int = Query(50, ge=1, le=V.MAX_HISTORY_LIMIT),
    offset: int = Query(0, ge=0),
) -> dict:
    arts = b.history_store.list_artifacts(
        mode=mode, project_id=project_id, since=from_, until=to,
        limit=limit, offset=offset,
    )
    return {"artifacts": [a.to_dict() for a in arts],
            "limit": limit, "offset": offset, "count": len(arts)}


@router.get("/artifacts/{artifact_id}")
def get_artifact(artifact_id: str, b: Backend = Depends(get_backend)) -> dict:
    art = b.history_store.get_artifact(artifact_id)
    if art is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return art.to_dict()


def _media_bases(b: Backend) -> list[Path]:
    """Katalogi, z których WOLNO serwować treść artefaktu: DATA_DIR (baza/historia)
    + skonfigurowany folder zapisu mediów. Plik spoza nich → odmowa."""
    bases = [Path(config.DATA_DIR)]
    try:
        bases.append(Path(b.history.get_save_path()))
    except Exception:
        pass
    out: list[Path] = []
    for base in bases:
        try:
            out.append(base.resolve())
        except Exception:
            continue
    return out


def _within(path: Path, base: Path) -> bool:
    try:
        return path.is_relative_to(base)
    except Exception:
        return False


@router.get("/artifacts/{artifact_id}/content")
def get_artifact_content(artifact_id: str, b: Backend = Depends(get_backend)):
    art = b.history_store.get_artifact(artifact_id)
    if art is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if not art.path:
        raise HTTPException(status_code=404, detail="Artifact has no local file")
    try:
        target = Path(art.path).resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="Bad artifact path")
    if not any(_within(target, base) for base in _media_bases(b)):
        # Plik poza dozwolonymi katalogami → nie serwujemy (anty-traversal).
        raise HTTPException(status_code=403, detail="Artifact path not allowed")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    # Bez `filename=` → serwowane INLINE (renderer wyświetla obraz/wideo wprost).
    return FileResponse(str(target), media_type=art.mime or "application/octet-stream")


# --- M9-B4: magistrala „send-to" — artefakt → gotowy blok wejściowy trybu --------
# Wynik jednego trybu staje się POPRAWNYM wejściem innego (rdzeń „all-in-one"):
#   image → blok vision (image_url, base64 z DYSKU — nie z sieci),
#   pdf/arkusz/plik → blok document,
#   text/code → blok text (cytat/kontekst).
# Blok jest gotowy dla czatu/agenta; renderer wstawia go do composera celu (F2).

_DOC_MIME_HINTS = (
    "pdf", "spreadsheet", "presentation", "officedocument",
    "ms-excel", "ms-powerpoint", "msword", "csv",
)


def _block_class(art: Artifact) -> Optional[str]:
    """Zaklasyfikuj artefakt do rodzaju bloku LLM: 'image' | 'text' | 'document'
    albo None (np. video/audio — brak bezpośredniego bloku wejściowego)."""
    mime = (art.mime or "").lower()
    if art.type == "image" or mime.startswith("image/"):
        return "image"
    if art.type in ("text", "code") or mime.startswith("text/") or mime == "application/json":
        return "text"
    if any(h in mime for h in _DOC_MIME_HINTS) or art.type == "file":
        return "document"
    return None


def _safe_artifact_file(art: Artifact, allowed_bases: list[Path]) -> Path:
    """Ścieżka pliku artefaktu po walidacji sandboxa (jak /content). Plik z DYSKU,
    nie z sieci (P1-14 / zasada B4). Rzuca HTTPException przy braku/ucieczce."""
    if not art.path:
        raise HTTPException(status_code=404, detail="Artifact has no local file")
    try:
        target = Path(art.path).resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="Bad artifact path")
    if not any(_within(target, base) for base in allowed_bases):
        raise HTTPException(status_code=403, detail="Artifact path not allowed")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return target


def build_input_payload(art: Artifact, allowed_bases: list[Path]) -> dict:
    """Zbuduj blok wejściowy LLM z artefaktu (B4). Zwraca dict z `block` (gotowy do
    treści wiadomości) oraz `data_uri`/`text` (do pipeline'u załączników / images[]).
    Czysty względem stanu — czyta tylko plik artefaktu z dozwolonych katalogów."""
    klass = _block_class(art)
    if klass is None:
        raise HTTPException(status_code=415,
                            detail=f"Artifact ({art.type}/{art.mime}) has no input block")
    target = _safe_artifact_file(art, allowed_bases)
    try:
        raw = target.read_bytes()
    except OSError:
        raise HTTPException(status_code=404, detail="File not readable")
    if len(raw) > V.MAX_INPUT_FILE_BYTES:
        raise HTTPException(status_code=413, detail="Artifact too large for input block")

    base = {"artifact_id": art.id, "type": art.type, "mode": art.mode,
            "mime": art.mime, "name": target.name}

    if klass == "text":
        text = raw.decode("utf-8", "replace")
        return {**base, "block": {"type": "text", "text": text}, "text": text}

    mime = art.mime or ("image/png" if klass == "image" else "application/octet-stream")
    data_uri = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"

    if klass == "image":
        # Reużyj walidatora data-URI (format + twardy limit rozmiaru, MAX_IMAGE_URI).
        try:
            V.validate_image_uri(data_uri)
        except ValueError as exc:
            raise HTTPException(status_code=413, detail=str(exc))
        block = {"type": "image_url", "image_url": {"url": data_uri}}
    else:  # document
        block = {"type": "document",
                 "document": {"data": data_uri, "mime": mime, "name": target.name}}
    return {**base, "block": block, "data_uri": data_uri}


@router.get("/artifacts/{artifact_id}/input-block")
def artifact_input_block(artifact_id: str, b: Backend = Depends(get_backend)) -> dict:
    """Send-to bus: zwróć gotowy blok wejściowy dla artefaktu (image→vision,
    pdf→document, text/code→text). Renderer wstawia `block` do composera celu."""
    art = b.history_store.get_artifact(artifact_id)
    if art is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return build_input_payload(art, _media_bases(b))
