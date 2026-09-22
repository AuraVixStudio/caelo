"""Deterministyczny dostawca lokalny do testow bez platnych wywolan."""

from __future__ import annotations

import base64
import itertools
from typing import Any, Iterable, Optional

from caelo_core.providers.base import (
    ImageGenerationRequest,
    ImageGenerationResult,
    MediaOutput,
    VideoGenerationRequest,
    VideoPollStatus,
    VideoSubmission,
)


# Poprawny PNG 1x1. MP4 zawiera kontenery ftyp + pusty moov, wystarczajace do
# sprawdzania przeplywu plikow bez binarnego fixture w repozytorium.
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
_MP4 = bytes.fromhex(
    "0000001c6674797069736f6d0000020069736f6d69736f326d703431000000086d6f6f76"
)


class MockProvider:
    provider_id = "mock"

    def __init__(self) -> None:
        self._ids = itertools.count(1)
        self._jobs: set[str] = set()

    def validate_connection(self) -> dict[str, Any]:
        return {"ok": True, "message": "Mock provider is always available."}

    def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        count = max(1, int(request.count))
        return ImageGenerationResult(tuple(
            MediaOutput(data=_PNG, mime_type="image/png", extension=".png")
            for _ in range(count)
        ), interaction_id=f"mock-image-{next(self._ids)}",
            metadata={"mock": True, "prompt": request.prompt})

    def submit_video(self, request: VideoGenerationRequest) -> VideoSubmission:
        remote_id = f"mock-video-{next(self._ids)}"
        self._jobs.add(remote_id)
        return VideoSubmission(self.provider_id, remote_id, request.model or "mock-video",
                               {"mock": True, "prompt": request.prompt})

    def poll_video(self, submission: VideoSubmission) -> VideoPollStatus:
        if submission.remote_id not in self._jobs:
            return VideoPollStatus("failed", error_message="Unknown mock video job")
        return VideoPollStatus(
            "succeeded",
            output=MediaOutput(data=_MP4, mime_type="video/mp4", extension=".mp4"),
            progress_percent=100,
            raw={"status": "done", "mock": True},
        )

    def complete_chat(self, messages: Iterable[dict[str, Any]], *,
                      model: Optional[str] = None, **options: Any) -> str:
        last = next((m.get("content", "") for m in reversed(list(messages))
                     if m.get("role") == "user"), "")
        return f"[mock] {last}"
