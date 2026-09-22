"""Trwała maszyna stanów: jeden scheduler, pula workerów, locki w SQLite."""

from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any, Callable, Optional

from caelo_core.jobs.recovery import UNKNOWN_MESSAGE, recover_jobs
from caelo_core.jobs.retry import retry_decision
from caelo_core.models.pricing import (
    DEFAULT_IMAGE_COST_PER_IMAGE,
    DEFAULT_VIDEO_COST_PER_SECOND,
    IMAGE_COST_PER_IMAGE,
    VIDEO_COST_PER_SECOND,
    estimate_cost,
    video_rate_per_second,
)
from caelo_core.storage.payloads import JobPayloadStore, strip_blob_params

_log = logging.getLogger("caelo.jobs")

__all__ = [
    "ACTIVE",
    "CANCELLED",
    "CostLimitExceeded",
    "DEFAULT_IMAGE_COST_PER_IMAGE",
    "DEFAULT_VIDEO_COST_PER_SECOND",
    "DONE",
    "FAILED",
    "GenJob",
    "GenJobCancelled",
    "GenJobManager",
    "GenJobQueueFull",
    "IMAGE_COST_PER_IMAGE",
    "IMAGE_OPS",
    "QUEUED",
    "RUNNING",
    "TERMINAL",
    "VIDEO_COST_PER_SECOND",
    "VIDEO_OPS",
    "estimate_cost",
    "video_rate_per_second",
]

QUEUED, RUNNING, DONE, FAILED, CANCELLED = (
    "queued",
    "running",
    "done",
    "failed",
    "cancelled",
)
TERMINAL = (DONE, FAILED, CANCELLED, "unknown_remote_state")
ACTIVE = (QUEUED, RUNNING)
IMAGE_OPS = ("text2img", "edit", "variation")
VIDEO_OPS = (
    "text2video",
    "img2video",
    "reference_to_video",
    "first_last_frame",
    "edit",
    "extend",
)
_RICH_ACTIVE = {
    "QUEUED",
    "PREPARING",
    "UPLOADING",
    "SUBMITTING",
    "SUBMITTED",
    "PROCESSING",
    "DOWNLOADING",
    "FINALIZING",
    "RETRY_WAIT",
    "RECOVERY_PENDING",
}


def _api_status(state: str) -> str:
    if state == "COMPLETED":
        return DONE
    if state == "FAILED":
        return FAILED
    if state == "CANCELLED":
        return CANCELLED
    if state == "UNKNOWN_REMOTE_STATE":
        return "unknown_remote_state"
    if state in {"QUEUED", "RETRY_WAIT"}:
        return QUEUED
    return RUNNING


class GenJobCancelled(Exception):
    pass


class GenJobQueueFull(Exception):
    pass


class CostLimitExceeded(Exception):
    pass


@dataclass
class GenJob:
    id: str
    kind: str
    op: str
    params: dict = field(default_factory=dict)
    status: str = QUEUED
    artifact_ids: list = field(default_factory=list)
    error: str = ""
    cost: float = 0.0
    project_id: Optional[str] = None
    created_at: float = 0.0
    updated_at: float = 0.0
    state: str = "QUEUED"
    generation_id: str = ""
    provider: str = "xai"
    remote_operation_id: Optional[str] = None
    remote_file_uri: Optional[str] = None
    remote_metadata: dict = field(default_factory=dict)
    attempt: int = 0
    max_attempts: int = 3
    progress: Optional[int] = None

    def to_dict(self, full: bool = False) -> dict:
        # dataclasses.asdict() wykonuje deepcopy całego params. Dla obrazów data-URI
        # oznaczało to setki MB chwilowej pamięci przy zwykłym odświeżeniu kolejki.
        result = {item.name: getattr(self, item.name) for item in fields(self)}
        result["artifact_ids"] = list(self.artifact_ids)
        result["remote_metadata"] = dict(self.remote_metadata)
        result["params"] = dict(self.params) if full else strip_blob_params(self.params)
        return result

    @classmethod
    def from_row(cls, row: dict, artifact_ids=None) -> "GenJob":
        state = str(row.get("state") or "QUEUED")
        return cls(
            id=row["id"],
            generation_id=row.get("generation_id") or row["id"],
            kind=row.get("kind") or row.get("queue_type"),
            op=row.get("operation") or row.get("op"),
            params=dict(row.get("request") or row.get("params") or {}),
            status=_api_status(state),
            artifact_ids=list(artifact_ids or row.get("artifact_ids") or []),
            error=row.get("last_error") or row.get("error") or "",
            cost=float(row.get("estimated_cost") or row.get("cost") or 0),
            project_id=row.get("project_id"),
            created_at=float(row.get("created_at") or 0),
            updated_at=float(row.get("updated_at") or 0),
            state=state,
            provider=row.get("provider") or "xai",
            remote_operation_id=row.get("remote_operation_id"),
            remote_file_uri=row.get("remote_file_uri"),
            remote_metadata=dict(row.get("remote_metadata") or {}),
            attempt=int(row.get("attempt") or 0),
            max_attempts=int(row.get("max_attempts") or 3),
            progress=row.get("progress"),
        )


Executor = Callable[[GenJob, threading.Event], list]


class GenJobManager:
    def __init__(
        self,
        executor: Executor,
        *,
        store: Any,
        workers: int = 2,
        max_active: int = 8,
        on_update: Optional[Callable[[GenJob], None]] = None,
        scheduler_interval: float = 0.25,
    ) -> None:
        self._executor, self._store, self._repos = executor, store, store.media
        self._max_active, self._on_update = int(max_active), on_update
        self._lock, self._stop = threading.RLock(), threading.Event()
        self._cancel: dict[str, threading.Event] = {}
        self._finished: dict[str, threading.Event] = {}
        self._work: queue.Queue = queue.Queue()
        self._worker_id = uuid.uuid4().hex[:8]
        self._scheduler_interval = scheduler_interval
        self._payloads = JobPayloadStore(Path(store.db_path).parent / "job_inputs")
        recover_jobs(self._repos)
        # Udana generacja nie może być ponawiana przez API, więc jej tymczasowe
        # wejścia są zbędne. Sprzątamy także pozostałości po twardym zamknięciu.
        for row in self._repos.jobs.list(
            active=False, limit=10_000, include_request=False
        ):
            if row.get("state") == "COMPLETED":
                self._payloads.cleanup(row["id"])
        for row in self._repos.jobs.list(active=True, limit=10_000):
            self._cancel[row["id"]] = threading.Event()
            self._finished[row["id"]] = threading.Event()
        self._threads = [
            threading.Thread(target=self._worker, name=f"genjob-{i}", daemon=True)
            for i in range(max(1, int(workers)))
        ]
        for thread in self._threads:
            thread.start()
        self._scheduler = threading.Thread(
            target=self._schedule, name="genjob-scheduler", daemon=True
        )
        self._scheduler.start()

    _SHUTDOWN = object()

    def submit(self, *, kind: str, op: str, params: dict, project_id=None) -> GenJob:
        with self._lock:
            if self._repos.jobs.count_active() >= self._max_active:
                raise GenJobQueueFull(
                    f"Too many active jobs (limit {self._max_active}). Wait for one to finish or cancel it."
                )
            now, job_id = time.time(), uuid.uuid4().hex
            cost = estimate_cost(kind, op, params or {})
            guard = getattr(self._executor, "guard_submit", None)
            if guard is not None:
                guard(kind=kind, op=op, params=params or {}, estimated_cost=cost)
            persisted_params = self._payloads.externalize(job_id, params or {})
            self._repos.generations.create(
                id=job_id,
                provider=str(params.get("provider") or "xai"),
                kind=kind,
                operation=op,
                request=persisted_params,
                status="QUEUED",
                project_id=project_id,
                estimated_cost=cost,
                created_at=now,
            )
            self._repos.jobs.create(
                id=job_id,
                generation_id=job_id,
                queue_type=kind,
                state="QUEUED",
                created_at=now,
            )
            self._cancel[job_id], self._finished[job_id] = (
                threading.Event(),
                threading.Event(),
            )
        job = self.get(job_id)
        self._notify(job)
        return job

    def _from(self, row):
        return (
            GenJob.from_row(
                row, self._repos.generations.artifact_ids(row["generation_id"])
            )
            if row
            else None
        )

    def get(self, job_id):
        return self._from(self._repos.jobs.get(job_id))

    def list_jobs(self, *, active=None, project_id=None, limit=50, offset=0):
        return [
            self._from(r)
            for r in self._repos.jobs.list(
                active=active, project_id=project_id, limit=limit, offset=offset,
                include_request=False,
            )
        ]

    def cancel(self, job_id):
        job = self.get(job_id)
        if not job or job.status in TERMINAL:
            return job
        self._cancel.setdefault(job_id, threading.Event()).set()
        if job.state in {"QUEUED", "RETRY_WAIT", "RECOVERY_PENDING"}:
            self._transition(job_id, "CANCELLED")
            self._signal_finished(job_id)
        return self.get(job_id)

    def retry(self, job_id):
        job = self.get(job_id)
        if not job:
            return None
        if job.status not in (FAILED, CANCELLED, "unknown_remote_state"):
            raise ValueError("Only failed, cancelled or uncertain jobs can be retried")
        return self.submit(
            kind=job.kind,
            op=job.op,
            params=self._payloads.materialize(job.params),
            project_id=job.project_id,
        )

    def remove(self, job_id):
        job = self.get(job_id)
        if not job or job.status in ACTIVE:
            return False
        self._repos.jobs.delete(job_id)
        self._payloads.cleanup(job_id)
        self._cancel.pop(job_id, None)
        self._finished.pop(job_id, None)
        return True

    def clear_finished(self, *, kind=None, project_id=None):
        terminal = self._repos.jobs.list(
            active=False, project_id=project_id, limit=10_000, include_request=False
        )
        if kind:
            terminal = [row for row in terminal if row.get("kind") == kind]
        n = self._repos.jobs.delete_terminal(kind=kind, project_id=project_id)
        for row in terminal:
            self._payloads.cleanup(row["id"])
        active = {j.id for j in self.list_jobs(active=True, limit=10_000)}
        for mapping in (self._cancel, self._finished):
            for key in list(mapping):
                if key not in active:
                    mapping.pop(key, None)
        return n

    def wait(self, job_id, timeout=30.0):
        event = self._finished.get(job_id)
        if event:
            event.wait(timeout)
        return self.get(job_id)

    def close(self, timeout=3.0):
        self._stop.set()
        self._scheduler.join(timeout)
        for _ in self._threads:
            self._work.put(self._SHUTDOWN)
        for thread in self._threads:
            thread.join(timeout)

    def transition(self, job_id: str, state: str, **fields):
        return self._transition(job_id, state, **fields)

    def persist_remote(
        self,
        job_id: str,
        *,
        remote_operation_id: str,
        remote_file_uri=None,
        remote_metadata=None,
    ):
        row = self._repos.jobs.get(job_id)
        self._repos.generations.update(
            row["generation_id"],
            remote_operation_id=remote_operation_id,
            remote_file_uri=remote_file_uri,
            remote_metadata=remote_metadata or {},
            status="SUBMITTED",
        )
        self._repos.jobs.update(job_id, state="SUBMITTED")

    def set_actual_cost(self, job_id: str, amount: float, *, remote_metadata=None) -> None:
        """Zastap koszt preflight rzeczywistym kosztem zwroconym przez API."""
        row = self._repos.jobs.get(job_id)
        if not row:
            return
        fields = {"estimated_cost": max(0.0, float(amount))}
        if remote_metadata is not None:
            fields["remote_metadata"] = dict(remote_metadata)
        self._repos.generations.update(row["generation_id"], **fields)

    def _schedule(self):
        while not self._stop.wait(self._scheduler_interval):
            now = time.time()
            for row in reversed(self._repos.jobs.list(active=True, limit=10_000)):
                state = row["state"]
                due = (
                    (
                        state == "QUEUED"
                        and (
                            row.get("next_run_at") is None or row["next_run_at"] <= now
                        )
                    )
                    or (state == "RETRY_WAIT" and (row.get("next_run_at") or 0) <= now)
                    or (
                        state in {"SUBMITTED", "PROCESSING"}
                        and (row.get("next_poll_at") or 0) <= now
                    )
                )
                if due and self._repos.jobs.try_lock(
                    row["id"],
                    self._worker_id,
                    stale_before=now - 120,
                    expected_state=state,
                ):
                    self._work.put(row["id"])

    def _worker(self):
        while True:
            job_id = self._work.get()
            if job_id is self._SHUTDOWN:
                self._work.task_done()
                return
            try:
                self._run_one(job_id)
            except Exception:
                _log.exception("generation worker crashed on %s", job_id)
            finally:
                self._work.task_done()

    def _run_one(self, job_id):
        job, cancel = (
            self.get(job_id),
            self._cancel.setdefault(job_id, threading.Event()),
        )
        if not job:
            return
        # SQLite przechowuje wyłącznie lekkie markery. Pełne data-URI istnieją w
        # pamięci tylko podczas rzeczywistego wywołania modelu.
        job = replace(job, params=self._payloads.materialize(job.params))
        if cancel.is_set():
            self._transition(job_id, "CANCELLED")
            self._signal_finished(job_id)
            return
        try:
            if hasattr(self._executor, "execute"):
                artifacts = self._executor.execute(job, cancel, self)
            else:
                self._transition(job_id, "PREPARING")
                # The compatibility callable must receive the same materialized
                # payload as executor objects.  Fetching the row again here would
                # reintroduce the lightweight file markers from SQLite.
                artifacts = self._executor(job, cancel)
            if artifacts is None:
                self._repos.jobs.unlock(job_id)
                return
            for artifact_id in list(artifacts or []):
                self._repos.generations.add_output(job.generation_id, artifact_id)
                source_ids = list(job.params.get("source_artifact_ids") or [])
                roles = list(job.params.get("source_artifact_roles") or job.params.get("reference_roles") or [])
                for index, source_id in enumerate(source_ids):
                    if not source_id:
                        continue
                    role = roles[index] if index < len(roles) else "reference"
                    self._repos.generations.add_reference(artifact_id, source_id, role)
            self._transition(job_id, "COMPLETED")
            self._payloads.cleanup(job_id)
            self._signal_finished(job_id)
        except GenJobCancelled:
            self._transition(job_id, "CANCELLED")
            self._signal_finished(job_id)
        except Exception as exc:
            fresh = self.get(job_id) or job
            attempt = fresh.attempt + 1
            # Timeout/zerwanie po wysłaniu może oznaczać, że dostawca przyjął płatne
            # żądanie. Bez uchwytu nie wolno zgadywać ani automatycznie wysyłać drugi raz.
            if fresh.state == "SUBMITTING" and not fresh.remote_operation_id:
                detail = f"{UNKNOWN_MESSAGE} ({str(exc) or exc.__class__.__name__})"
                self._transition(
                    job_id, "UNKNOWN_REMOTE_STATE", attempt=attempt, last_error=detail
                )
                self._signal_finished(job_id)
                return
            decision = retry_decision(exc, fresh.provider, attempt, fresh.max_attempts)
            if decision.retry:
                self._repos.jobs.update(
                    job_id,
                    state="RETRY_WAIT",
                    attempt=attempt,
                    next_run_at=time.time() + decision.delay_seconds,
                    locked_at=None,
                    worker_id=None,
                    last_error=decision.message,
                )
                self._repos.generations.update(
                    fresh.generation_id, status="RETRY_WAIT", error=decision.message
                )
            else:
                self._transition(
                    job_id, "FAILED", attempt=attempt, last_error=decision.message
                )
                self._signal_finished(job_id)

    def _transition(self, job_id, state, **fields):
        if state not in _RICH_ACTIVE:
            fields.update(locked_at=None, worker_id=None)
        fields["state"] = state
        self._repos.jobs.update(job_id, **fields)
        row = self._repos.jobs.get(job_id)
        self._repos.generations.update(
            row["generation_id"],
            status=state,
            error=fields.get("last_error", row.get("error") or ""),
        )
        job = self._from(self._repos.jobs.get(job_id))
        self._notify(job)
        return job

    def _notify(self, job):
        if self._on_update and job:
            try:
                self._on_update(job)
            except Exception:
                _log.debug("gen_job on_update hook raised", exc_info=True)

    def _signal_finished(self, job_id):
        event = self._finished.get(job_id)
        if event:
            event.set()
