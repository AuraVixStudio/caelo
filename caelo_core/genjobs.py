"""M11-B1: jednolity, asynchroniczny mechanizm generacji (obraz + wideo).

`GenJob` = zadanie async ze statusem; każde wyjście rejestrowane jako **Artifact
M9** (kręgosłup huba). Worker w wątku — jak blokujące wywołania xAI w `/chat/stream`
— więc długie wideo NIE blokuje pętli serwera. Rekordy persistowane w SQLite z M9
(`history_store`), więc kolejka i biblioteka przeżywają restart i są przeszukiwalne.

**Egzekutor jest WSTRZYKIWANY** (warstwa tras/`Backend`): `genjobs.py` NIE importuje
`api_manager`/`state`, więc nie ma cyklicznego importu i silnik jest testowalny na
atrapie (zgodne z regułą CLAUDE.md o cienkiej warstwie endpoint/auth). Egzekutor
dostaje `(job, cancel_event)` i zwraca listę `artifact_id`; może rzucić
`GenJobCancelled`, by zadanie skończyło jako `cancelled` (nie `failed`).

Transport statusu to **REST polling** (baza wg `PLAN_M11`): worker robi pełną pętlę
pollingu wideo po stronie serwera, a renderer odpytuje `/genjobs`. `on_update` jest
opcjonalnym haczykiem (np. push przez `WsStream`) — domyślnie nieużywany.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional

_log = logging.getLogger("caelo.genjobs")

# Statusy zadania (cykl życia: queued → running → done|failed|cancelled).
QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"
TERMINAL = (DONE, FAILED, CANCELLED)
ACTIVE = (QUEUED, RUNNING)

# Rodzaje i operacje (walidacja miękka — UI/trasy pilnują dozwolonych wartości).
IMAGE_OPS = ("text2img", "edit", "variation")
VIDEO_OPS = ("text2video", "img2video", "edit", "extend")

# P1-D: klucze `params`, które mogą nieść base64 data-URI (obraz: refs `images` /
# pojedynczy `image`; wideo: `video`/`image`). Te bloby (do 12 MB obraz, 64 MB wideo)
# rozdmuchują `GET /genjobs` do dziesiątek MB na każdy tick pollingu → reset połączenia.
_BLOB_PARAM_KEYS = ("images", "image", "video")


def _strip_blobs(params: dict) -> dict:
    """Płytka kopia `params` z data-URI zastąpionymi krótkim placeholderem. Zostawia
    nietknięte URL-e https i pozostałe pola (prompt/n/resolution/model…). Tylko do
    ODPOWIEDZI listy/statusu; egzekutor i `retry` używają pełnych `params` z bazy."""
    def _omit(v):
        if isinstance(v, str) and v.startswith("data:"):
            return f"<data-uri {len(v)} bytes omitted>"
        return v

    out = dict(params or {})
    for k in _BLOB_PARAM_KEYS:
        if k not in out:
            continue
        v = out[k]
        if isinstance(v, list):
            out[k] = [_omit(e) for e in v]
        else:
            out[k] = _omit(v)
    return out

# --- szacunek kosztu wg cennika xAI (transparentność BYO-key) -----------------
# Stawki PER-MODEL wg oficjalnego cennika xAI (https://docs.x.ai/developers/pricing,
# zweryfikowane 2026-06-07). Obraz rozliczany za sztukę, wideo za sekundę; "quality"
# i preview są droższe. Służą do pokazania userowi rzędu wielkości jego wydatków
# (BYO-key), nie do rozliczeń — faktyczne zużycie potwierdza konto xAI.
IMAGE_COST_PER_IMAGE = {
    "grok-imagine-image": 0.02,          # $0.02 / image (standard, domyślny)
    "grok-imagine-image-quality": 0.05,  # $0.05 / image (wyższa jakość)
}
VIDEO_COST_PER_SECOND = {
    "grok-imagine-video": 0.05,              # $0.050 / sec
    "grok-imagine-video-1.5-preview": 0.08,  # $0.080 / sec (domyślny)
}
# Stawka, gdy model nieznany/niepodany → model domyślny z config.py
# (DEFAULT_IMAGE_MODEL = grok-imagine-image, DEFAULT_VIDEO_MODEL = …-video-1.5-preview).
DEFAULT_IMAGE_COST_PER_IMAGE = 0.02
DEFAULT_VIDEO_COST_PER_SECOND = 0.08


def estimate_cost(kind: str, op: str, params: dict) -> float:
    """Zgrubny szacunek kosztu zadania (USD) z parametrów. Czysta funkcja.
    Stawka zależy od `params["model"]` (cennik xAI); nieznany/niepodany model →
    stawka modelu domyślnego.

    ROAD-3.6-d: wideo rozliczane jest za **długość WYJŚCIA**, nie za żądany
    `duration`. `text2video`/`img2video` produkują klip o długości `duration`,
    ale `edit` zachowuje długość ŹRÓDŁA, a `extend` to ŹRÓDŁO + dodane sekundy —
    więc dla nich liczymy z `source_duration` (gdy klient go zna). Bez niego
    spadamy na `duration` (brak regresji: niedoszacowanie, nie crash). Funkcja
    pozostaje czysta (bez importu `api_manager`/`state`)."""
    try:
        model = params.get("model") or ""
        if kind == "image":
            n = int(params.get("n", 1) or 1)
            rate = IMAGE_COST_PER_IMAGE.get(model, DEFAULT_IMAGE_COST_PER_IMAGE)
            return round(rate * max(1, n), 4)
        if kind == "video":
            rate = VIDEO_COST_PER_SECOND.get(model, DEFAULT_VIDEO_COST_PER_SECOND)
            dur = int(params.get("duration", 6) or 6)
            src = int(params.get("source_duration", 0) or 0)
            if op == "edit":
                billed = src or dur          # edycja nie zmienia długości źródła
            elif op == "extend":
                billed = src + dur if src else dur   # źródło + dodane sekundy
            else:
                billed = dur                 # text2video / img2video
            return round(rate * max(1, billed), 4)
    except (TypeError, ValueError):
        pass
    return 0.0


class GenJobCancelled(Exception):
    """Egzekutor zgłasza ją, gdy zauważy ustawiony `cancel_event` (→ status cancelled)."""


class GenJobQueueFull(Exception):
    """Przekroczono limit aktywnych zadań w kolejce (B4)."""


@dataclass
class GenJob:
    """Rekord zadania generacji (PLAN_M11-B1)."""
    id: str
    kind: str           # "image" | "video"
    op: str             # text2img | edit | variation | text2video | img2video
    params: dict = field(default_factory=dict)
    status: str = QUEUED
    artifact_ids: list = field(default_factory=list)
    error: str = ""
    cost: float = 0.0
    project_id: Optional[str] = None
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self, full: bool = False) -> dict:
        """Słownik zadania. `full=False` (domyślnie, wszystkie odpowiedzi REST) usuwa
        data-URI z `params` (P1-D). `full=True` (egzekutor/retry/wewnętrznie) zwraca
        pełne `params`."""
        d = asdict(self)
        if not full:
            d["params"] = _strip_blobs(self.params)
        return d

    @classmethod
    def from_row(cls, row: dict) -> "GenJob":
        return cls(
            id=row["id"], kind=row["kind"], op=row["op"],
            params=dict(row.get("params") or {}), status=row["status"],
            artifact_ids=list(row.get("artifact_ids") or []), error=row.get("error") or "",
            cost=float(row.get("cost") or 0.0), project_id=row.get("project_id"),
            created_at=float(row.get("created_at") or 0.0),
            updated_at=float(row.get("updated_at") or 0.0),
        )


# Egzekutor: (job, cancel_event) -> list[artifact_id]. Rzuca przy błędzie;
# `GenJobCancelled`, jeśli zauważy anulowanie.
Executor = Callable[[GenJob, threading.Event], list]


class GenJobManager:
    """Kolejka + pula workerów dla `GenJob`. Bezpieczna dla wielu wątków.

    `store` to magazyn M9 (`history_store.HistoryStore` lub kompatybilny) — ŹRÓDŁO
    PRAWDY o rekordach zadań (lista przeżywa restart). Pamięć podręczna trzyma tylko
    eventy anulowania i sygnały zakończenia (do `wait`)."""

    def __init__(self, executor: Executor, *, store: Any, workers: int = 2,
                 max_active: int = 8, on_update: Optional[Callable[[GenJob], None]] = None) -> None:
        self._executor = executor
        self._store = store
        self._max_active = int(max_active)
        self._on_update = on_update
        self._lock = threading.RLock()
        self._cancel: dict[str, threading.Event] = {}
        self._finished: dict[str, threading.Event] = {}
        self._queue: "queue.Queue[str]" = queue.Queue()
        # Zadania zawieszone przy poprzednim uruchomieniu (restart sidecara) są stale:
        # worker ich nie dokończy. Oznacz je jako failed("interrupted"), by UI nie
        # pokazywało wiecznego „running".
        self._reap_stale()
        self._threads = [
            threading.Thread(target=self._worker, name=f"genjob-{i}", daemon=True)
            for i in range(max(1, int(workers)))
        ]
        for t in self._threads:
            t.start()

    # Sentinel kolejki: sygnał dla workera, by zakończył pętlę (porządne zamknięcie).
    _SHUTDOWN = object()

    # --- API publiczne --------------------------------------------------------

    def submit(self, *, kind: str, op: str, params: dict,
               project_id: Optional[str] = None) -> GenJob:
        """Zakolejkuj zadanie. Przekroczony limit aktywnych → `GenJobQueueFull` (B4)."""
        with self._lock:
            if self._store.count_active_gen_jobs() >= self._max_active:
                raise GenJobQueueFull(
                    f"Too many active jobs (limit {self._max_active}). "
                    "Wait for one to finish or cancel it."
                )
            now = time.time()
            job = GenJob(
                id=uuid.uuid4().hex, kind=kind, op=op, params=dict(params or {}),
                status=QUEUED, cost=estimate_cost(kind, op, params or {}),
                project_id=project_id, created_at=now, updated_at=now,
            )
            self._cancel[job.id] = threading.Event()
            self._finished[job.id] = threading.Event()
            self._persist(job)
            self._queue.put(job.id)
        self._notify(job)
        return job

    def get(self, job_id: str) -> Optional[GenJob]:
        row = self._store.get_gen_job(job_id)
        return GenJob.from_row(row) if row else None

    def list_jobs(self, *, active: Optional[bool] = None,
                  project_id: Optional[str] = None, limit: int = 50,
                  offset: int = 0) -> list[GenJob]:
        rows = self._store.list_gen_jobs(active=active, project_id=project_id,
                                         limit=limit, offset=offset)
        return [GenJob.from_row(r) for r in rows]

    def cancel(self, job_id: str) -> Optional[GenJob]:
        """Anuluj zadanie. Queued → od razu `cancelled`; running → sygnał dla
        egzekutora (wideo: pętla pollingu przerywa; obraz: dokończy bieżące wywołanie)."""
        job = self.get(job_id)
        if job is None or job.status in TERMINAL:
            return job
        with self._lock:
            # S31-a: re-czytaj status POD lockiem — bez tego okno między get() a set()
            # pozwalało „wskrzesić" zadanie (cancel widzi QUEUED, worker już zrobił RUNNING).
            job = self.get(job_id)
            if job is None or job.status in TERMINAL:
                return job
            ev = self._cancel.get(job_id)
            if ev is not None:
                ev.set()
            if job.status == QUEUED:
                job = self._set(job, CANCELLED)
                self._signal_finished(job_id)
        return self.get(job_id)

    def retry(self, job_id: str) -> Optional[GenJob]:
        """Ponów zadanie failed/cancelled jako NOWE (te same kind/op/params)."""
        job = self.get(job_id)
        if job is None:
            return None
        if job.status not in (FAILED, CANCELLED):
            raise ValueError("Only failed or cancelled jobs can be retried")
        return self.submit(kind=job.kind, op=job.op, params=job.params,
                           project_id=job.project_id)

    def remove(self, job_id: str) -> bool:
        """Usuń jedno ZAKOŃCZONE zadanie z listy. Aktywnego nie ruszamy (worker je
        trzyma) → False. Artefakty NIE są usuwane (zostają w galerii)."""
        job = self.get(job_id)
        if job is None or job.status in ACTIVE:
            return False
        self._store.delete_gen_job(job_id)
        self._cancel.pop(job_id, None)
        self._finished.pop(job_id, None)
        return True

    def clear_finished(self, *, kind: Optional[str] = None,
                       project_id: Optional[str] = None) -> int:
        """Wyczyść z listy wszystkie zakończone zadania (opcjonalnie po `kind`/projekcie).
        Aktywne zostają; artefakty NIE są usuwane. Zwraca liczbę usuniętych."""
        n = self._store.delete_terminal_gen_jobs(kind=kind, project_id=project_id)
        # S31-b: snapshot active_ids + prune POD lockiem (serializacja vs submit(), które
        # pisze _cancel/_finished pod tym samym lockiem) — inaczej można wypruć eventy
        # świeżo zasubmitowanego zadania (jego cancel()/wait() przestałyby działać).
        with self._lock:
            active_ids = {j.id for j in self.list_jobs(active=True, limit=1000)}
            for d in (self._cancel, self._finished):
                for k in [k for k in list(d) if k not in active_ids]:
                    d.pop(k, None)
        return n

    def wait(self, job_id: str, timeout: float = 30.0) -> Optional[GenJob]:
        """Zablokuj do osiągnięcia stanu terminalnego (dla selfchecków/testów)."""
        ev = self._finished.get(job_id)
        if ev is not None:
            ev.wait(timeout)
        return self.get(job_id)

    def close(self, timeout: float = 3.0) -> None:
        """Porządne zatrzymanie workerów (sentinel + join). Dla testów/zamknięcia —
        bieżący `Backend` jest długożyjący, więc w produkcji zwykle niewołane."""
        for _ in self._threads:
            self._queue.put(self._SHUTDOWN)
        for t in self._threads:
            t.join(timeout)

    # --- wnętrze --------------------------------------------------------------

    def _worker(self) -> None:
        while True:
            job_id = self._queue.get()
            if job_id is self._SHUTDOWN:
                self._queue.task_done()
                return
            try:
                self._run_one(job_id)
            except Exception:  # noqa: BLE001 — worker nie może umrzeć po cichu
                _log.exception("genjob worker crashed on %s", job_id)
            finally:
                self._queue.task_done()

    def _run_one(self, job_id: str) -> None:
        job = self.get(job_id)
        if job is None:
            return
        cancel = self._cancel.get(job_id) or threading.Event()
        # S31-a: przejście QUEUED->RUNNING (i sprawdzenie cancel) ATOMOWO pod lockiem,
        # by nie ścigać się z cancel() (które też re-czyta status pod tym samym lockiem).
        with self._lock:
            job = self.get(job_id)
            if job is None:
                return
            if cancel.is_set() or job.status != QUEUED:
                if job.status == QUEUED:
                    self._set(job, CANCELLED)
                self._signal_finished(job_id)
                return
            job = self._set(job, RUNNING)
        try:
            artifact_ids = list(self._executor(job, cancel) or [])
            job.artifact_ids = artifact_ids
            self._set(job, DONE)
        except GenJobCancelled:
            self._set(job, CANCELLED)
        except Exception as exc:  # noqa: BLE001
            _log.warning("genjob %s failed: %s", job_id, exc, exc_info=True)
            job.error = str(exc) or exc.__class__.__name__
            self._set(job, FAILED)
        finally:
            self._signal_finished(job_id)

    def _set(self, job: GenJob, status: str) -> GenJob:
        job.status = status
        job.updated_at = time.time()
        # P1-D: po starcie zmienia się tylko status/artefakty/error — NIE przepisuj
        # wielomegabajtowego `params` (data-URI) pod globalnym lockiem przy każdej
        # tranzycji. Wiersz wstawił już `submit`/`_persist`.
        self._persist_status(job)
        self._notify(job)
        return job

    def _persist(self, job: GenJob) -> None:
        try:
            self._store.upsert_gen_job(
                id=job.id, kind=job.kind, op=job.op, params=job.params,
                status=job.status, artifact_ids=job.artifact_ids, error=job.error,
                cost=job.cost, project_id=job.project_id,
                created_at=job.created_at, updated_at=job.updated_at,
            )
        except Exception:  # noqa: BLE001 — persistencja nie może wywrócić workera
            _log.warning("could not persist gen_job %s", job.id, exc_info=True)

    def _persist_status(self, job: GenJob) -> None:
        """P1-D: aktualizacja samego statusu/wyników (bez `params`). Fallback do
        pełnego `_persist`, jeśli magazyn nie ma metody (kompatybilność atrap)."""
        upd = getattr(self._store, "update_gen_job_status", None)
        if upd is None:
            self._persist(job)
            return
        try:
            upd(id=job.id, status=job.status, artifact_ids=job.artifact_ids,
                error=job.error, updated_at=job.updated_at)
        except Exception:  # noqa: BLE001 — persistencja nie może wywrócić workera
            _log.warning("could not persist gen_job status %s", job.id, exc_info=True)

    def _notify(self, job: GenJob) -> None:
        if self._on_update is not None:
            try:
                self._on_update(job)
            except Exception:  # noqa: BLE001
                _log.debug("gen_job on_update hook raised", exc_info=True)

    def _signal_finished(self, job_id: str) -> None:
        ev = self._finished.get(job_id)
        if ev is not None:
            ev.set()

    def _reap_stale(self) -> None:
        """Zadania utknięte w queued/running z poprzedniego procesu → failed."""
        try:
            stale = self._store.list_gen_jobs(active=True, limit=1000)
        except Exception:  # noqa: BLE001
            return
        for row in stale:
            job = GenJob.from_row(row)
            job.status = FAILED
            job.error = "interrupted (backend restarted)"
            job.updated_at = time.time()
            self._persist(job)
