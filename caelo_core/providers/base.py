"""Neutralne kontrakty dostawcow modeli i mediow.

Warstwa kolejki oraz trasy HTTP zalezą od tych kontraktow, a nie od SDK/API
konkretnego dostawcy. Kontrakty sa synchroniczne, bo obecny backend wykonuje
blokujace wywolania w kontrolowanych workerach.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class MediaOutput:
    """Jedno wygenerowane medium: zdalny URL albo gotowe bajty."""

    url: Optional[str] = None
    data: Optional[bytes] = None
    mime_type: str = "application/octet-stream"
    extension: str = ""

    def __post_init__(self) -> None:
        if bool(self.url) == bool(self.data is not None):
            raise ValueError("MediaOutput requires exactly one of url or data")


@dataclass(frozen=True)
class ImageGenerationRequest:
    prompt: str
    operation: str = "text2img"
    model: Optional[str] = None
    count: int = 1
    aspect_ratio: str = "auto"
    resolution: str = "1k"
    images: tuple[str, ...] = ()
    reference_roles: tuple[str, ...] = ()
    quality: Optional[str] = None
    thinking_level: Optional[str] = None
    search_grounding: bool = False
    mime_type: str = "image/png"
    output_format: Optional[str] = None
    output_compression: Optional[int] = None
    background: Optional[str] = None
    moderation: Optional[str] = None


@dataclass(frozen=True)
class ImageGenerationResult:
    outputs: tuple[MediaOutput, ...]
    interaction_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VideoGenerationRequest:
    prompt: str
    operation: str = "text2video"
    model: Optional[str] = None
    duration: Optional[int] = 6
    resolution: str = "480p"
    aspect_ratio: str = "Original"
    image: Optional[str] = None
    last_image: Optional[str] = None
    video: Optional[str] = None
    reference_images: tuple[str, ...] = ()
    reference_roles: tuple[str, ...] = ()
    generate_audio: bool = True
    seed: Optional[int] = None
    negative_prompt: Optional[str] = None
    previous_interaction_id: Optional[str] = None


@dataclass(frozen=True)
class VideoSubmission:
    provider: str
    remote_id: str
    model: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VideoPollStatus:
    """Znormalizowany status niezalezny od slownika konkretnego API."""

    state: str  # queued | running | succeeded | failed | expired
    output: Optional[MediaOutput] = None
    progress_percent: Optional[int] = None
    error_message: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def done(self) -> bool:
        return self.state in {"succeeded", "failed", "expired"}


@dataclass(frozen=True)
class ChatCompletionResult:
    """Neutralny wynik jednej tury czatu niezależny od formatu providera."""

    text: str
    citations: tuple[dict[str, Any], ...] = ()
    usage: dict[str, Any] = field(default_factory=dict)
    tool_calls: int = 0


@runtime_checkable
class MediaProvider(Protocol):
    provider_id: str

    def validate_connection(self) -> dict[str, Any]: ...


@runtime_checkable
class ImageProvider(MediaProvider, Protocol):
    def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResult: ...


@runtime_checkable
class VideoProvider(MediaProvider, Protocol):
    def submit_video(self, request: VideoGenerationRequest) -> VideoSubmission: ...

    def poll_video(self, submission: VideoSubmission) -> VideoPollStatus: ...


@runtime_checkable
class ChatProvider(MediaProvider, Protocol):
    def complete_chat(
        self,
        messages: Iterable[dict[str, Any]],
        *,
        model: Optional[str] = None,
        **options: Any,
    ) -> Any: ...

    def stream_chat(
        self,
        messages: Iterable[dict[str, Any]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        reasoning_effort: Optional[str] = None,
        search_grounding: bool = False,
        on_delta: Optional[Callable[[str, str], None]] = None,
        on_tool: Optional[Callable[[dict[str, Any]], None]] = None,
        stop_flag: Optional[Callable[[], bool]] = None,
    ) -> ChatCompletionResult: ...
