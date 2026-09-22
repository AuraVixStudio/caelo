"""Jedna ścieżka generacji dla xAI i Google, sterowana trwałą kolejką."""

from __future__ import annotations

import time

from caelo_core.jobs.queue import GenJobCancelled
from caelo_core.providers import VideoGenerationRequest, VideoSubmission


class GenerationApplicationService:
    def __init__(self, backend) -> None:
        self.backend = backend

    def guard_submit(
        self, *, kind: str, op: str, params: dict, estimated_cost: float
    ) -> None:
        if kind not in {"image", "video"}:
            raise ValueError(f"unsupported generation kind: {kind}")
        provider = str(params.get("provider") or "xai")
        self.backend.get_provider(
            provider
        )  # lokalna walidacja adaptera, bez wywołania sieci
        settings = self.backend.read_settings()
        limit = float(settings.get("media_monthly_soft_limit_usd") or 0)
        if limit > 0:
            from datetime import datetime
            from caelo_core.jobs.queue import CostLimitExceeded

            now = datetime.now()
            since = datetime(now.year, now.month, 1).timestamp()
            spent = self.backend.history_store.media.usage.estimated_since(since)
            if spent + estimated_cost > limit:
                raise CostLimitExceeded(
                    f"Monthly media cost limit (${limit:.2f}) would be exceeded."
                )

    def execute(self, job, cancel, queue):
        if cancel.is_set():
            raise GenJobCancelled()
        if job.kind == "image":
            queue.transition(job.id, "PREPARING")
            queue.transition(job.id, "SUBMITTING")
            artifacts = self.backend._run_image_job(job, cancel, strict_save=True)
            queue.transition(job.id, "FINALIZING")
            actual_cost = self._actual_image_cost(job)
            if actual_cost is not None:
                queue.set_actual_cost(
                    job.id, actual_cost, remote_metadata=job.remote_metadata
                )
            self._record_usage(job, actual_cost=actual_cost)
            return artifacts
        if job.kind != "video":
            raise ValueError(f"unknown generation kind: {job.kind}")
        return self._video(job, cancel, queue)

    def _video(self, job, cancel, queue):
        provider = self.backend.get_provider(job.provider)
        if job.remote_operation_id:
            submission = VideoSubmission(
                job.provider,
                job.remote_operation_id,
                job.params.get("model") or None,
                dict(job.remote_metadata or {}),
            )
        else:
            queue.transition(job.id, "PREPARING")
            if cancel.is_set():
                raise GenJobCancelled()
            queue.transition(job.id, "SUBMITTING")
            submission = provider.submit_video(self._video_request(job))
            # Ta operacja MUSI nastąpić przed pollingiem. Po restarcie obecność handle
            # oznacza bezpieczne wznowienie, a jego brak przy SUBMITTING = stan niepewny.
            queue.persist_remote(
                job.id,
                remote_operation_id=submission.remote_id,
                remote_metadata=submission.metadata,
            )
        if cancel.is_set():
            raise GenJobCancelled()
        queue.transition(job.id, "PROCESSING")
        status = provider.poll_video(submission)
        if cancel.is_set():
            raise GenJobCancelled()
        if status.state in {"queued", "running"}:
            queue.transition(
                job.id,
                "PROCESSING",
                progress=status.progress_percent,
                next_poll_at=time.time() + 5.0,
            )
            return None
        if status.state in {"failed", "expired"}:
            raise RuntimeError(status.error_message or f"video job {status.state}")
        if status.output is None:
            raise RuntimeError("video job finished without output")
        queue.transition(job.id, "DOWNLOADING", progress=100)
        results = self.backend.save_provider_outputs(
            [status.output],
            job.params.get("prompt", ""),
            "video",
            ".mp4",
            project_id=job.project_id,
            meta_extra={
                "gen_op": job.op,
                "model": job.params.get("model") or "",
                "provider": job.provider,
                "remote_operation_id": submission.remote_id,
            },
            strict=True,
        )
        queue.transition(job.id, "FINALIZING", progress=100)
        self._record_usage(job)
        return [r["artifact_id"] for r in results if r.get("artifact_id")]

    @staticmethod
    def _video_request(job):
        p = job.params
        return VideoGenerationRequest(
            prompt=p.get("prompt", ""),
            operation=job.op,
            model=p.get("model") or None,
            duration=int(p.get("duration", 6) or 6),
            resolution=p.get("resolution", "480p"),
            aspect_ratio=p.get("aspect_ratio", "Original"),
            image=p.get("image"),
            last_image=p.get("last_image"),
            video=p.get("video"),
            reference_images=tuple(p.get("reference_images") or ()),
            reference_roles=tuple(p.get("reference_roles") or ()),
            generate_audio=bool(p.get("generate_audio", True)),
            seed=p.get("seed"),
            negative_prompt=p.get("negative_prompt") or None,
            previous_interaction_id=p.get("previous_interaction_id") or None,
        )

    @staticmethod
    def _actual_image_cost(job):
        if job.provider != "openai" or job.kind != "image":
            return None
        from caelo_core.models.pricing import openai_image_cost_from_usage

        metadata = job.remote_metadata if isinstance(job.remote_metadata, dict) else {}
        usage = metadata.get("usage") or {}
        return openai_image_cost_from_usage(
            usage, has_image_input=bool(job.params.get("images"))
        )

    def _record_usage(self, job, *, actual_cost=None):
        units = (
            float(job.params.get("n", 1) or 1)
            if job.kind == "image"
            else float(job.params.get("duration", 0) or 0)
        )
        self.backend.history_store.media.usage.record(
            generation_id=job.generation_id,
            provider=job.provider,
            model=str(job.params.get("model") or ""),
            kind=job.kind,
            units=units,
            unit_name="image" if job.kind == "image" else "second",
            estimated_cost=job.cost,
            actual_cost=actual_cost,
        )
