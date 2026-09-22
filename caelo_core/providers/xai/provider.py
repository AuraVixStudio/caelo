"""Adapter xAI nad istniejacym, niezmienianym ``APIManager`` (ADR-7)."""

from __future__ import annotations

from typing import Any, Iterable, Optional

from caelo_core.providers.base import (
    ImageGenerationRequest,
    ImageGenerationResult,
    MediaOutput,
    VideoGenerationRequest,
    VideoPollStatus,
    VideoSubmission,
)
from caelo_core.providers.errors import ProviderError, normalize_provider_error


class XAIProvider:
    provider_id = "xai"

    def __init__(self, api: Any) -> None:
        self.api = api

    def validate_connection(self) -> dict[str, Any]:
        try:
            self.api.list_models()
            return {"ok": True, "message": "xAI connection is available."}
        except Exception as exc:  # noqa: BLE001
            err = normalize_provider_error(exc, self.provider_id)
            return {"ok": False, "message": str(err), "error": err.to_dict()}

    def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        try:
            if request.operation == "text2img":
                urls = self.api.generate_image(
                    request.prompt, request.count, request.aspect_ratio, request.resolution,
                    model=request.model, quality=request.quality,
                )
            elif request.operation in ("edit", "variation"):
                if not request.images:
                    raise ValueError(f"{request.operation} requires reference images")
                urls = self.api.edit_image_b64(
                    request.prompt, list(request.images), request.count,
                    request.aspect_ratio, request.resolution,
                    model=request.model, quality=request.quality,
                )
            else:
                raise ValueError(f"Unsupported image operation: {request.operation}")
            return ImageGenerationResult(tuple(
                MediaOutput(url=url, mime_type="image/png", extension=".png") for url in urls
            ))
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise normalize_provider_error(exc, self.provider_id) from exc

    def submit_video(self, request: VideoGenerationRequest) -> VideoSubmission:
        try:
            if request.operation == "edit":
                if not request.video:
                    raise ValueError("edit requires a source video")
                remote_id = self.api.edit_video_job(
                    request.prompt, request.video, model=request.model)
            elif request.operation == "extend":
                if not request.video:
                    raise ValueError("extend requires a source video")
                remote_id = self.api.extend_video_job(
                    request.prompt, request.video, duration=request.duration or None,
                    model=request.model,
                )
            elif request.operation in ("text2video", "img2video", "reference_to_video"):
                remote_id = self.api.create_video_job(
                    request.prompt, int(request.duration or 6), request.resolution, request.aspect_ratio,
                    None, model=request.model, image_data_uri=request.image,
                    reference_images=list(request.reference_images) or None,
                )
            else:
                raise ValueError(f"Unsupported video operation: {request.operation}")
            return VideoSubmission(self.provider_id, str(remote_id), request.model)
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise normalize_provider_error(exc, self.provider_id) from exc

    def poll_video(self, submission: VideoSubmission) -> VideoPollStatus:
        try:
            raw = self.api.poll_video_status(submission.remote_id) or {}
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise normalize_provider_error(exc, self.provider_id) from exc

        provider_state = str(raw.get("status") or "").lower()
        state = {
            "queued": "queued",
            "pending": "queued",
            "in_progress": "running",
            "processing": "running",
            "running": "running",
            "done": "succeeded",
            "succeeded": "succeeded",
            "failed": "failed",
            "expired": "expired",
        }.get(provider_state, "running")
        video = raw.get("video") or {}
        url = video.get("url") if isinstance(video, dict) else None
        output = MediaOutput(url=url, mime_type="video/mp4", extension=".mp4") if url else None
        progress = raw.get("progress") or raw.get("progress_percent")
        return VideoPollStatus(
            state=state,
            output=output,
            progress_percent=int(progress) if isinstance(progress, (int, float)) else None,
            error_message=str(raw.get("error") or "") or None,
            raw=raw,
        )

    def complete_chat(self, messages: Iterable[dict[str, Any]], *,
                      model: Optional[str] = None, **options: Any) -> Any:
        try:
            return self.api.chat_completion(
                list(messages), model=model or "grok-4",
                temperature=float(options.get("temperature", 0.7)),
            )
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise normalize_provider_error(exc, self.provider_id) from exc
