"""Trasy historii i artefaktów huba (M9-B3) — REST do czytania kręgosłupa.

  GET /history                — lista zdarzeń + filtry (q FTS / mode / project_id / from / to) + paginacja
  GET /artifacts              — lista artefaktów (te same filtry)
  GET /artifacts/{id}         — metadane artefaktu
  GET /artifacts/{id}/content — strumień pliku artefaktu (inline)

Magazyn: `caelo_core.history_store` (SQLite/FTS5) przez `Backend.history_store`.
Wszystkie trasy są pod globalnym guardem tokenu w `server.py` (P1-10, fail-closed).
Limity wejścia z `validation.py` (naruszenie → 422). Treść artefaktu jest serwowana
tylko z dozwolonych katalogów (DATA_DIR / folder zapisu mediów) — plik poza nimi
jest ODMAWIANY (defense-in-depth: artefakt z podejrzaną ścieżką nie wyciąga
dowolnego pliku z dysku).
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, field_validator

import config  # type: ignore

from caelo_core import validation as V
from caelo_core.history_store import Artifact
from caelo_core.state import Backend, get_backend
from caelo_core.storage.images import fit_image_to_uri_budget
from caelo_core.storage.thumbnails import create_image_thumbnail

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


def _iso(ts) -> str:
    """Epoka (sekundy) → czytelny znacznik UTC. Puste, gdy nie da się sparsować."""
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:  # noqa: BLE001
        return ""


def events_to_markdown(events: list[dict], *, title: str = "Caelo history export") -> str:
    """M19-B10: serializuj zdarzenia historii huba (to_dict + opcjonalny 'meta') do
    Markdown. CZYSTA funkcja (bez I/O) — łatwa do testów. Każde zdarzenie → sekcja:
    tryb + znacznik czasu, opcjonalny model/prompt (z meta) i zapisany tekst (odpowiedź)."""
    out: list[str] = [f"# {title}", "", f"_{len(events)} event(s)_", ""]
    for ev in events:
        mode = str(ev.get("mode") or "?")
        ts = _iso(ev.get("created_at"))
        out.append(f"## {mode}" + (f" — {ts}" if ts else ""))
        meta = ev.get("meta") if isinstance(ev.get("meta"), dict) else {}
        model = meta.get("model")
        prompt = meta.get("prompt")
        if model:
            out.append(f"*Model: {model}*")
        if prompt:
            out += ["", "**Prompt:**", "", str(prompt).strip()]
        text = (ev.get("text") or "").strip()
        if text:
            out += ["", "**Response:**", "", text]
        out += ["", "---", ""]
    return "\n".join(out).rstrip() + "\n"


@router.get("/history/export")
def export_history(
    b: Backend = Depends(get_backend),
    q: Optional[str] = Query(None, max_length=V.MAX_HISTORY_QUERY),
    mode: Optional[str] = Query(None, max_length=V.MAX_ID_LEN),
    project_id: Optional[str] = Query(None, max_length=V.MAX_ID_LEN),
    from_: Optional[float] = Query(None, alias="from"),
    to: Optional[float] = Query(None),
    limit: int = Query(V.MAX_HISTORY_LIMIT, ge=1, le=V.MAX_HISTORY_LIMIT),
    offset: int = Query(0, ge=0),
) -> Response:
    """M19-B10: eksport historii (te same filtry co /history) do Markdown. Dołącza
    prompt/model z `meta` (czytane z FTS). Zwraca text/markdown jako załącznik."""
    events = b.history_store.list_events(
        q=q, mode=mode, project_id=project_id, since=from_, until=to,
        limit=limit, offset=offset,
    )
    dicts = [e.to_dict() for e in events]
    metas = b.history_store.event_metas([d["id"] for d in dicts])
    for d in dicts:
        d["meta"] = metas.get(d["id"], {})
    md = events_to_markdown(dicts)
    return Response(
        content=md, media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="caelo-history.md"'},
    )


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


class ArtifactPatch(BaseModel):
    favorite: Optional[bool] = None
    tags: Optional[list[str]] = Field(None, max_length=20)


class ReferenceImageUpload(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    data: str = Field(..., max_length=V.MAX_IMAGE_URI)

    @field_validator("data")
    @classmethod
    def _image_data_uri(cls, value: str) -> str:
        return V.validate_image_uri(value)


_REFERENCE_IMAGE_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/avif": ".avif",
}
_MAX_REFERENCE_IMAGE_BYTES = (V.MAX_IMAGE_URI * 3) // 4


def _save_reference_image(*, raw: bytes, mime: str, name: str, b: Backend) -> dict:
    mime = (mime or "").split(";", 1)[0].strip().lower()
    extension = _REFERENCE_IMAGE_EXTENSIONS.get(mime)
    if extension is None:
        raise HTTPException(status_code=415, detail="Unsupported reference image format")
    if not raw:
        raise HTTPException(status_code=400, detail="Reference image is empty")
    if len(raw) > _MAX_REFERENCE_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Reference image is too large")

    artifact_id = uuid.uuid4().hex
    library_dir = Path(config.DATA_DIR) / "reference_library"
    try:
        library_dir.mkdir(parents=True, exist_ok=True)
        target = library_dir / f"{artifact_id}{extension}"
        temporary = library_dir / f".{artifact_id}.tmp"
        temporary.write_bytes(raw)
        temporary.replace(target)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Could not save reference image") from exc

    display_name = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    (library_dir / "Thumbnails").mkdir(parents=True, exist_ok=True)
    thumb_path = create_image_thumbnail(target, library_dir, max_size=384)
    try:
        artifact = b.history_store.add_artifact(
            id=artifact_id,
            type="image",
            mode="reference",
            mime="image/jpeg" if mime == "image/jpg" else mime,
            path=str(target),
            thumb_path=thumb_path,
            meta={"name": display_name or f"reference{extension}", "source": "import"},
            project_id=None,
        )
    except Exception as exc:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(status_code=500, detail="Could not register reference image") from exc
    return {"artifact": artifact.to_dict()}


@router.post("/reference-library")
def upload_reference_image(body: ReferenceImageUpload,
                           b: Backend = Depends(get_backend)) -> dict:
    """Copy an imported reference image into Caelo's persistent media store."""
    try:
        header, encoded = body.data.split(",", 1)
        mime = header[5:].split(";", 1)[0].lower()
        raw = base64.b64decode(encoded, validate=True)
    except HTTPException:
        raise
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="Invalid reference image data")
    return _save_reference_image(raw=raw, mime=mime, name=body.name, b=b)


@router.post("/reference-library/file")
async def upload_reference_file(
    request: Request,
    name: str = Query(..., min_length=1, max_length=512),
    b: Backend = Depends(get_backend),
) -> dict:
    """Lżejszy import binarny używany przez desktop — bez JSON i inflacji base64."""
    content_length = request.headers.get("content-length", "")
    if content_length.isdigit() and int(content_length) > _MAX_REFERENCE_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Reference image is too large")
    raw = await request.body()
    return _save_reference_image(
        raw=raw,
        mime=request.headers.get("content-type", ""),
        name=name,
        b=b,
    )


@router.patch("/artifacts/{artifact_id}")
def update_artifact(artifact_id: str, body: ArtifactPatch,
                    b: Backend = Depends(get_backend)) -> dict:
    if b.history_store.get_artifact(artifact_id) is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if body.favorite is not None:
        b.history_store.set_artifact_favorite(artifact_id, body.favorite)
    if body.tags is not None:
        try:
            b.history_store.set_artifact_tags(artifact_id, body.tags)
        except KeyError:
            raise HTTPException(status_code=404, detail="Artifact not found")
    art = b.history_store.get_artifact(artifact_id)
    return art.to_dict()


@router.get("/artifacts/{artifact_id}/lineage")
def get_artifact_lineage(artifact_id: str, b: Backend = Depends(get_backend)) -> dict:
    if b.history_store.get_artifact(artifact_id) is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return b.history_store.artifact_lineage(artifact_id)


def _media_bases(b: Backend) -> list[Path]:
    """Katalogi, z których WOLNO serwować/kasować treść artefaktu: DATA_DIR + folder
    zapisu mediów (S31-k: wspólny helper z `state.delete_project`; P2-3.2-b: korzeń FS
    odrzucany w `media_paths.media_bases`)."""
    from caelo_core.media_paths import media_bases
    try:
        save = b.history.get_save_path()
    except Exception:
        save = None
    return media_bases(save)


def _within(path: Path, base: Path) -> bool:
    from caelo_core.media_paths import within
    return within(path, base)


@router.delete("/artifacts/{artifact_id}")
def delete_artifact(artifact_id: str, b: Backend = Depends(get_backend)) -> dict:
    """Usuń artefakt: rekord + plik z dysku (jeśli leży w dozwolonych katalogach
    mediów — anty-traversal). Plik spoza nich NIE jest kasowany. M11 follow-up:
    pozwala wyczyścić „Recent" / galerię, gdy media się nazbierają."""
    art = b.history_store.get_artifact(artifact_id)
    if art is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    deleted_file = False
    for stored_path in dict.fromkeys((art.path, art.thumb_path)):
        if not stored_path:
            continue
        try:
            target = Path(stored_path).resolve()
            if target.is_file() and any(_within(target, base) for base in _media_bases(b)):
                target.unlink()
                deleted_file = True
        except OSError:
            pass
    b.history_store.delete_artifact(artifact_id)
    return {"ok": True, "deleted_file": deleted_file}


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


@router.get("/artifacts/{artifact_id}/thumbnail")
def get_artifact_thumbnail(artifact_id: str, b: Backend = Depends(get_backend)):
    art = b.history_store.get_artifact(artifact_id)
    if art is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if not art.path and not art.thumb_path:
        raise HTTPException(status_code=404, detail="Artifact has no thumbnail")

    # Stare rekordy mogą wskazywać gotową miniaturę. Nowe wyniki zapisują w folderze
    # użytkownika wyłącznie oryginał, więc mały WEBP tworzymy leniwie w cache Caelo.
    # Cache leży w DATA_DIR, nigdy obok wygenerowanych obrazów.
    stored_path = art.thumb_path
    generated_cache = False
    if not stored_path and art.type == "image" and art.path:
        try:
            source = Path(art.path).resolve()
        except Exception:
            raise HTTPException(status_code=400, detail="Bad artifact path")
        if not any(_within(source, base) for base in _media_bases(b)):
            raise HTTPException(status_code=403, detail="Artifact path not allowed")
        if not source.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        cache_root = Path(config.DATA_DIR) / "thumbnail_cache"
        expected = cache_root / "Thumbnails" / f"{artifact_id}.webp"
        try:
            stale = not expected.is_file() or expected.stat().st_mtime < source.stat().st_mtime
        except OSError:
            stale = True
        if stale:
            stored_path = create_image_thumbnail(
                source, cache_root, max_size=512, cache_key=artifact_id
            )
        else:
            stored_path = str(expected)
        generated_cache = bool(stored_path)
    if not stored_path:
        stored_path = art.path
    try:
        target = Path(stored_path).resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="Bad thumbnail path")
    if not any(_within(target, base) for base in _media_bases(b)):
        raise HTTPException(status_code=403, detail="Thumbnail path not allowed")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    mime = "image/webp" if (art.thumb_path or generated_cache) else (art.mime or "application/octet-stream")
    return FileResponse(str(target), media_type=mime)


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
    if klass == "image":
        # Obraz 2K/4K (kilkanaście MB PNG) nie mieści się w MAX_IMAGE_URI. Zamiast
        # odrzucić „Send to…", przygotuj mniejszą kopię wejściową — oryginał na
        # dysku zostaje nietknięty (jak lib/imageCompress.ts po stronie renderera).
        raw, mime = fit_image_to_uri_budget(raw, mime, V.MAX_IMAGE_URI)
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
    # `mime` opisuje data_uri, więc po przekodowaniu obrazu musi je odzwierciedlać.
    return {**base, "mime": mime, "block": block, "data_uri": data_uri}


@router.get("/artifacts/{artifact_id}/input-block")
def artifact_input_block(artifact_id: str, b: Backend = Depends(get_backend)) -> dict:
    """Send-to bus: zwróć gotowy blok wejściowy dla artefaktu (image→vision,
    pdf→document, text/code→text). Renderer wstawia `block` do composera celu."""
    art = b.history_store.get_artifact(artifact_id)
    if art is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return build_input_payload(art, _media_bases(b))
