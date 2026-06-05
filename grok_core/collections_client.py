"""Klient xAI **vector stores / files** — M10-B5 (kolekcje / `file_search`).

Trwała wiedza projektu: dokumenty wgrane do **vector store** (kolekcji) per projekt,
przeszukiwane w wielu rozmowach narzędziem serwerowym `file_search` (Responses API,
rodzina grok-4). Endpointy zgodne z OpenAI (xAI je mirroruje — patrz `responses_client`):

  POST /v1/files                          (multipart: file + purpose) -> {id}
  POST /v1/vector_stores                  ({name})                    -> {id}
  POST /v1/vector_stores/{id}/files       ({file_id})                 -> {id}
  DELETE /v1/vector_stores/{id}/files/{file_id}

ZASADY (jak `responses_client.py`): cienka warstwa endpoint/auth — root `api_manager.py`
NIETKNIĘTY; Bearer z `api_key_provider()` (OAuth → klucz → XAI_API_KEY) tylko do api.x.ai;
jawne timeouty (P1-4). Limity weryfikacji: realne `/v1/vector_stores` jest za przechwytywaniem
TLS w sandboxie — kształt potwierdza użytkownik z kluczem. `api_smoke` mockuje HTTP, więc
przepływ (upload → store → file_search) jest sprawdzony bez sieci. To **stretch** M10.
"""

from __future__ import annotations

import logging
from typing import Callable, List, Optional

import requests  # type: ignore

import config  # type: ignore

log = logging.getLogger(__name__)

TIMEOUT_UPLOAD = 180   # upload pliku (PDF/arkusz) bywa duży
TIMEOUT_API = 60       # create store / attach / delete


class CollectionUpstreamError(Exception):
    """Błąd z endpointu vector store/files xAI — niesie **status HTTP** + krótki
    fragment odpowiedzi (do logu serwera). Pozwala odróżnić „xAI nie wspiera kolekcji"
    (404) od złego pola/`purpose` (400/422) czy auth (401/403). UI dostaje sam status
    + krótki komunikat (nie surowe szczegóły xAI — P1-13)."""

    def __init__(self, status: int, what: str, body: str = "") -> None:
        super().__init__(f"{what} (HTTP {status})")
        self.status = status
        self.what = what
        self.body = body


def _auth_header(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}"}


def _base() -> str:
    return config.API_BASE


def _check(r, what: str, *, want_id: bool = True) -> Optional[str]:
    """Wspólna obsługa odpowiedzi xAI: błąd HTTP / brak `id` → CollectionUpstreamError
    z czytelnym statusem (i krótkim body do logu)."""
    if r.status_code >= 400:
        body = ""
        try:
            body = (r.text or "")[:400]
        except Exception:
            pass
        raise CollectionUpstreamError(r.status_code, what, body)
    if not want_id:
        return None
    try:
        r.encoding = "utf-8"
        data = r.json()
    except Exception:
        raise CollectionUpstreamError(r.status_code, f"{what}: non-JSON response",
                                      (getattr(r, "text", "") or "")[:400])
    fid = data.get("id") if isinstance(data, dict) else None
    if not fid:
        raise CollectionUpstreamError(r.status_code, f"{what}: response has no 'id'",
                                      str(data)[:400])
    return fid


def upload_file(data: bytes, filename: str, api_key_provider: Callable[[], str],
                purpose: str = "assistants") -> str:
    """Wgraj plik (multipart) → zwróć `file_id`. `purpose='assistants'` = plik do
    retrievalu (vector store). Content-Type ustawia `requests` (boundary multipart)."""
    api_key = api_key_provider()
    files = {"file": (filename or "document", data)}
    r = requests.post(f"{_base()}/files", headers=_auth_header(api_key),
                      data={"purpose": purpose}, files=files, timeout=TIMEOUT_UPLOAD)
    return _check(r, "upload file")


def create_vector_store(name: str, api_key_provider: Callable[[], str],
                        file_ids: Optional[List[str]] = None) -> str:
    """Utwórz vector store (kolekcję) → zwróć `vector_store_id`."""
    api_key = api_key_provider()
    payload: dict = {"name": name or "collection"}
    if file_ids:
        payload["file_ids"] = file_ids
    headers = {**_auth_header(api_key), "Content-Type": "application/json"}
    r = requests.post(f"{_base()}/vector_stores", headers=headers, json=payload,
                      timeout=TIMEOUT_API)
    return _check(r, "create vector store")


def add_file_to_store(vector_store_id: str, file_id: str,
                      api_key_provider: Callable[[], str]) -> None:
    """Dołącz wgrany plik do vector store (indeksowanie po stronie xAI)."""
    api_key = api_key_provider()
    headers = {**_auth_header(api_key), "Content-Type": "application/json"}
    r = requests.post(f"{_base()}/vector_stores/{vector_store_id}/files",
                      headers=headers, json={"file_id": file_id}, timeout=TIMEOUT_API)
    _check(r, "attach file to vector store", want_id=False)


def delete_file_from_store(vector_store_id: str, file_id: str,
                           api_key_provider: Callable[[], str]) -> None:
    """Usuń plik z vector store. Błędy połykane (best-effort — lokalny rekord i tak
    znika; osierocony plik po stronie xAI nie jest krytyczny)."""
    api_key = api_key_provider()
    try:
        requests.delete(f"{_base()}/vector_stores/{vector_store_id}/files/{file_id}",
                        headers=_auth_header(api_key), timeout=TIMEOUT_API)
    except Exception:
        log.warning("Could not delete file %s from vector store %s", file_id,
                    vector_store_id, exc_info=True)


def file_search_tool(vector_store_ids: List[str]) -> Optional[dict]:
    """Narzędzie serwerowe `file_search` dla Responses (przeszukuje kolekcję).
    None, gdy brak vector store (nie dołączaj pustego narzędzia)."""
    ids = [v for v in (vector_store_ids or []) if v]
    if not ids:
        return None
    return {"type": "file_search", "vector_store_ids": ids}
