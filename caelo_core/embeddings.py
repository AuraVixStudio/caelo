"""Klient xAI **Embeddings** (`POST /v1/embeddings`) — M19-B8.

Cienka warstwa endpoint/auth (jak `responses_client.py` vs root `api_manager.py`) dla
pamięci hybrydowej (B8): zamienia tekst na wektor, który `history_store` trzyma w
`event_embeddings` i przeszukuje brute-force cosine (bez `sqlite-vec`/torch).

ZASADY (CLAUDE.md):
- Klient ŻYJE TU, NIE w root `api_manager.py` (nie restrukturyzujemy rdzenia).
- **Precedencja auth bez zmian**: `api_key_provider()` (OAuth → klucz → XAI_API_KEY),
  wstrzykiwany przez wołającego (jak `state.get_api_key`). Bearer tylko do api.x.ai.
- **JAWNE UTF-8** przy dekodowaniu JSON odpowiedzi (konwencja repo).
- Format żądania/odpowiedzi zgodny z OpenAI (`{"model","input"}` →
  `{"data":[{"embedding":[...],"index":n}], "usage":{...}}`). Parser TOLERANCYJNY na
  kształt — wire-format xAI potwierdza użytkownik (sandbox blokuje `api.x.ai`).

**SPIKE (PLAN_M19_TIER2 §9):** czy `POST /v1/embeddings` działa na naszym auth, jaki
model/wymiary/koszt — weryfikuje `probe()` na maszynie użytkownika
(`python -m caelo_core ... ` / `tools/embeddings_check.py`). Reszta B8 (magazyn, KNN,
hybryda, wstrzyknięcie) jest sprawdzona bez sieci na **stub-embedderze**.
"""

from __future__ import annotations

import logging
from typing import Callable, List, Optional, Sequence

import requests  # type: ignore

import config  # type: ignore

log = logging.getLogger(__name__)

EMBED_TIMEOUT = 60  # sekundy — embedding to krótkie żądanie (nie streaming)


class EmbeddingError(Exception):
    """Błąd wywołania embeddings (sieć / status / nieoczekiwany kształt odpowiedzi)."""


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _parse_embeddings(data: dict, expected: int) -> List[List[float]]:
    """Wyłuskaj wektory z odpowiedzi (format OpenAI), uporządkowane wg `index`.
    Rzuca `EmbeddingError`, gdy kształt nie pasuje albo liczba wektorów ≠ `expected`."""
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise EmbeddingError("embeddings response has no 'data'")
    ordered = sorted(items, key=lambda it: it.get("index", 0) if isinstance(it, dict) else 0)
    vecs: List[List[float]] = []
    for it in ordered:
        emb = it.get("embedding") if isinstance(it, dict) else None
        if not isinstance(emb, list) or not emb:
            raise EmbeddingError("embeddings response item has no 'embedding'")
        vecs.append([float(x) for x in emb])
    if len(vecs) != expected:
        raise EmbeddingError(f"expected {expected} embeddings, got {len(vecs)}")
    return vecs


def embed_texts(
    texts: Sequence[str],
    *,
    api_key_provider: Callable[[], str],
    model: Optional[str] = None,
    base: Optional[str] = None,
    timeout: int = EMBED_TIMEOUT,
) -> List[List[float]]:
    """Zamień listę tekstów na wektory (batch). Zwraca listę wektorów w kolejności
    wejścia. Rzuca `EmbeddingError` na błąd sieci/statusu/kształtu — wołający (warstwa
    pamięci) POŁYKA go, by nigdy nie wywrócić ścieżki użytkownika."""
    texts = [str(t or "") for t in texts]
    if not texts:
        return []
    api_key = api_key_provider()
    if not api_key:
        raise EmbeddingError("no API key available for embeddings")
    url = f"{base or config.API_BASE}/embeddings"
    payload = {"model": model or config.EMBED_MODEL, "input": texts}
    try:
        r = requests.post(url, headers=_headers(api_key), json=payload, timeout=timeout)
        r.raise_for_status()
        r.encoding = "utf-8"  # konwencja repo — nie pozwól requests zgadywać
        data = r.json()
    except EmbeddingError:
        raise
    except Exception as exc:  # noqa: BLE001 — sieć/HTTP/JSON; opakuj w jeden typ
        raise EmbeddingError(f"embeddings request failed: {exc}") from exc
    return _parse_embeddings(data, expected=len(texts))


def embed_text(text: str, *, api_key_provider: Callable[[], str],
               model: Optional[str] = None, base: Optional[str] = None) -> List[float]:
    """Wektor pojedynczego tekstu (wygodny wrapper na `embed_texts`)."""
    return embed_texts([text], api_key_provider=api_key_provider, model=model, base=base)[0]


def probe(api_key_provider: Callable[[], str], *, model: Optional[str] = None,
          base: Optional[str] = None) -> dict:
    """SPIKE: sprawdź czy `POST /v1/embeddings` działa na naszym auth. NIE rzuca —
    zwraca raport `{ok, model, dim, error}` do wypisania użytkownikowi (uruchamiane na
    maszynie usera, gdzie `api.x.ai` jest osiągalne)."""
    mdl = model or config.EMBED_MODEL
    try:
        vec = embed_text("hello", api_key_provider=api_key_provider, model=mdl, base=base)
        return {"ok": True, "model": mdl, "dim": len(vec), "error": ""}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "model": mdl, "dim": 0, "error": str(exc)[:300]}
