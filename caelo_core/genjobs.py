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

# --- zgrubny szacunek kosztu (transparentność BYO-key, NIE cennik xAI) --------
# Obraz tani, wideo droższe (rośnie z długością). Wartości celowo ostrożne; służą
# do pokazania userowi rzędu wielkości jego wydatków, nie do rozliczeń.
IMAGE_COST_PER_OUTPUT = 0.02   # USD za pojedynczy wygenerowany obraz
VIDEO_COST_PER_SECOND = 0.10   # USD za sekundę wideo


def estimate_cost(kind: str, op: str, params: dict) -> float:
    """Zgrubny szacunek kosztu zadania (USD) z parametrów. Czysta funkcja."""
    try:
        if kind == "image":
            n = int(params.get("n", 1) or 1)
            return round(IMAGE_COST_PER_OUTPUT * max(1, n), 4)
        if kind == "video":
            dur = int(params.get("duration", 6) or 6)
            return round(VIDEO_COST_PER_SECOND * max(1, dur), 4)
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

    def to_dict(self) -> dict:
        return asdict(self)

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
        # Przytnij słowniki eventów do wciąż aktywnych zadań (reszta to martwy balast).
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
        # Anulowane, zanim worker je podniósł (race z cancel()).
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
        self._persist(job)
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
