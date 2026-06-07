"""Pamięć hybrydowa agenta (M19-B8) — embed + indeks + recall + wstrzyknięcie.

Spina trzy warstwy bez wprowadzania zależności sieciowych do magazynu:
- `history_store.HistoryStore` — czysty magazyn wektorów + KNN/hybryda (bez sieci),
- `embed_fn` — WSTRZYKIWANY embedder (batch `texts -> wektory`), zwykle
  `caelo_core.embeddings.embed_texts` z `api_key_provider` (jak egzekutor w genjobs),
- formatowanie top-K wspomnień do system promptu agenta (1. tura, po CAELO.md).

Zasady: **opt-in** (domyślnie wyłączone — koszt embeddingów + prywatność); każdy błąd
embeddera/magazynu jest POŁYKANY (logowany), nigdy nie wywraca tury użytkownika.
Indeksowanie jest synchroniczne TU (testowalne na stubie) — wołający (`Backend`) puszcza
je w wątku w tle, by nie blokować ścieżki użytkownika.
"""

from __future__ import annotations

import logging
from typing import Callable, List, Optional, Sequence

log = logging.getLogger(__name__)

EmbedFn = Callable[[Sequence[str]], List[List[float]]]

_MAX_SNIPPET = 280  # przytnij pojedyncze wspomnienie, by nie zalać kontekstu


class MemoryIndex:
    """Indeks pamięci semantycznej nad `HistoryStore` z wstrzykniętym embedderem."""

    def __init__(self, store, embed_fn: EmbedFn, *, enabled: bool = False,
                 max_results: int = 5, min_score: float = 0.55) -> None:
        self._store = store
        self._embed_fn = embed_fn
        self.enabled = bool(enabled)
        self.max_results = int(max_results)
        self.min_score = float(min_score)

    # --- indeksowanie ---------------------------------------------------------
    def index_event(self, event_id: str, text: str) -> bool:
        """Policz wektor `text` i zapisz pod `event_id`. Zwraca True przy sukcesie.
        No-op (False), gdy wyłączone / pusty tekst / błąd (połknięty)."""
        if not self.enabled or not event_id or not (text or "").strip():
            return False
        try:
            vec = self._embed_fn([text])[0]
            self._store.set_event_embedding(event_id, vec)
            return True
        except Exception:  # noqa: BLE001 — embedder/sieć/magazyn; nigdy nie wywracaj ścieżki
            log.warning("Memory: could not index event %s", event_id, exc_info=True)
            return False

    # --- recall ---------------------------------------------------------------
    def recall(self, query: str, *, project_id: Optional[str] = None,
               k: Optional[int] = None):
        """Lista najtrafniejszych `HistoryEvent` dla zapytania (hybryda KNN+FTS).
        `[]`, gdy wyłączone / pusty query / błąd embeddera (wtedy degraduje do pustki —
        nie chcemy hałasu z samego FTS bez sygnału semantycznego)."""
        if not self.enabled or not (query or "").strip():
            return []
        limit = k or self.max_results
        try:
            qvec = self._embed_fn([query])[0]
        except Exception:  # noqa: BLE001
            log.warning("Memory: could not embed query for recall", exc_info=True)
            return []
        try:
            return self._store.hybrid_search(
                q_text=query, query_vec=qvec, k=limit,
                project_id=project_id, min_score=self.min_score,
            )
        except Exception:  # noqa: BLE001
            log.warning("Memory: hybrid_search failed", exc_info=True)
            return []

    # --- wstrzyknięcie do system promptu (1. tura agenta) ---------------------
    def injected_text(self, query: str, *, project_id: Optional[str] = None) -> str:
        """Sformatuj top-K wspomnień jako blok do system promptu. `""`, gdy brak."""
        events = self.recall(query, project_id=project_id)
        if not events:
            return ""
        lines: List[str] = []
        for ev in events:
            snippet = " ".join((ev.text or "").split())
            if len(snippet) > _MAX_SNIPPET:
                snippet = snippet[:_MAX_SNIPPET] + "…"
            if snippet:
                lines.append(f"- [{ev.mode}] {snippet}")
        if not lines:
            return ""
        return (
            "--- Relevant memory (semantically related past activity; use only if it "
            "helps the current task; ignore if irrelevant) ---\n" + "\n".join(lines)
        )
