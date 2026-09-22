"""Fasada jednego dostawcy Google dla obrazu i wideo."""

from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping, Optional
import threading

from caelo_core.providers.base import (
    ChatCompletionResult,
    ImageGenerationRequest,
    ImageGenerationResult,
    VideoGenerationRequest,
    VideoPollStatus,
    VideoSubmission,
)

from .chat import GoogleChatProvider
from .client import GoogleClient
from .image import GoogleImageProvider
from .tools import GoogleAgentTools
from .video import GoogleVideoProvider


class GoogleProvider:
    provider_id = "google"

    def __init__(self, settings: Callable[[], Mapping[str, Any]], *,
                 client: Optional[GoogleClient] = None, remote_cache=None) -> None:
        self.client = client or GoogleClient(settings)
        self.chat = GoogleChatProvider(self.client)
        self.agent = GoogleAgentTools(self.client)
        self.images = GoogleImageProvider(self.client)
        self.videos = GoogleVideoProvider(self.client, remote_cache)
        self._submissions: dict[str, VideoSubmission] = {}
        self._lock = threading.RLock()

    def validate_connection(self) -> dict[str, Any]:
        return self.client.validate_connection()

    def stream_chat(self, messages: Iterable[dict[str, Any]], **options: Any) -> ChatCompletionResult:
        return self.chat.stream_chat(messages, **options)

    def complete_chat(self, messages: Iterable[dict[str, Any]], *,
                      model: Optional[str] = None, **options: Any) -> str:
        return self.chat.complete_chat(messages, model=model, **options)

    def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        return self.images.generate_image(request)

    def submit_video(self, request: VideoGenerationRequest) -> VideoSubmission:
        submission = self.videos.submit_video(request)
        with self._lock:
            self._submissions[submission.remote_id] = submission
        return submission

    def poll_video(self, submission: VideoSubmission) -> VideoPollStatus:
        if not submission.metadata:
            with self._lock:
                submission = self._submissions.get(submission.remote_id, submission)
        status = self.videos.poll_video(submission)
        if status.done:
            with self._lock:
                self._submissions.pop(submission.remote_id, None)
        return status
