"""Testy akceptacyjne fazy 1: kontrakty, xAI, mock, katalog i cennik."""

from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from caelo_core.models.capabilities import CapabilityError
from caelo_core.models.pricing import estimate_cost
from caelo_core.models.registry import get_model_registry
from caelo_core.providers import ImageGenerationRequest, VideoGenerationRequest
from caelo_core.providers.errors import ErrorCategory, normalize_provider_error
from caelo_core.providers.ids import (
    ACTIVE_AGENT_PROVIDER_IDS,
    ACTIVE_CHAT_PROVIDER_IDS,
    normalize_provider_id,
)
from caelo_core.providers.mock import MockProvider
from caelo_core.providers.xai import XAIProvider
from caelo_core.routes.models import list_capabilities, list_models, list_providers


class FakeXaiApi:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def list_models(self):
        return ["grok-4"]

    def generate_image(self, prompt, n, ratio, resolution, model=None, quality=None):
        self.calls.append(("image", prompt, n, ratio, resolution, model, quality))
        return ["https://example.test/image.png"] * n

    def edit_image_b64(self, prompt, images, n, ratio, resolution, model=None, quality=None):
        self.calls.append(("edit-image", prompt, images, n, ratio, resolution, model, quality))
        return ["https://example.test/edit.png"]

    def create_video_job(self, prompt, duration, resolution, ratio, image_path=None,
                         model=None, image_data_uri=None, reference_images=None):
        self.calls.append(("video", prompt, duration, resolution, ratio, model,
                           image_data_uri, reference_images))
        return "video-1"

    def poll_video_status(self, job_id):
        return {"status": "done", "video": {"url": "https://example.test/video.mp4"}}

    def chat_completion(self, messages, model="grok-4", temperature=0.7):
        return "ok"


def test_text_provider_ids_are_shared_and_unknown_values_fail_closed() -> None:
    assert ACTIVE_CHAT_PROVIDER_IDS == ("xai", "google", "openai")
    assert ACTIVE_AGENT_PROVIDER_IDS == ("xai", "google", "openai")
    assert normalize_provider_id(" GOOGLE ", ACTIVE_CHAT_PROVIDER_IDS) == "google"
    assert normalize_provider_id("openai", ACTIVE_CHAT_PROVIDER_IDS) == "openai"
    assert normalize_provider_id("openai", ACTIVE_AGENT_PROVIDER_IDS) == "openai"


def test_registry_exposes_providers_models_and_capabilities() -> None:
    registry = get_model_registry()
    assert {p.id for p in registry.providers()} == {"xai", "mock", "google", "openai"}
    image = registry.resolve("xai", "image", "grok-imagine-image-2.0")
    assert image.capabilities.supports_quality is True
    assert image.capabilities.max_reference_images == 5
    assert "text2img" in image.capabilities.operations
    assert "1080p" in registry.resolve(
        "xai", "video", "grok-imagine-video-1.5"
    ).capabilities.resolutions
    assert registry.resolve("xai", "chat", "grok-4.6").capabilities.thinking_levels == (
        "low", "medium", "high", "xhigh",
    )
    assert registry.resolve(
        "xai", "chat", "grok-4.20-multi-agent-0309"
    ).capabilities.thinking_levels == ("low", "medium", "high", "xhigh")
    assert registry.resolve(
        "xai", "chat", "grok-4.20-0309-non-reasoning"
    ).capabilities.thinking is False


def test_capability_guard_rejects_unsupported_settings_before_provider_call() -> None:
    registry = get_model_registry()
    with pytest.raises(CapabilityError):
        registry.validate(
            "xai", "image", "text2img",
            {"resolution": "8k", "quality": "ultra"},
            "grok-imagine-image",
        )
    # Bez jawnego modelu rejestr wybiera model bazowy zdolny do edit/extend.
    selected = registry.validate("xai", "video", "edit", {}, None)
    assert selected.id == "grok-imagine-video"


def test_xai_adapter_preserves_existing_api_manager_calls_and_normalizes_poll() -> None:
    api = FakeXaiApi()
    provider = XAIProvider(api)
    result = provider.generate_image(ImageGenerationRequest(
        prompt="cat", model="grok-imagine-image-2.0", count=2, quality="low",
    ))
    assert len(result.outputs) == 2
    assert api.calls[0] == (
        "image", "cat", 2, "auto", "1k", "grok-imagine-image-2.0", "low"
    )

    submission = provider.submit_video(VideoGenerationRequest(
        prompt="run", model="grok-imagine-video-1.5",
        reference_images=("data:image/png;base64,AA",),
    ))
    status = provider.poll_video(submission)
    assert submission.remote_id == "video-1"
    assert status.state == "succeeded"
    assert status.output and status.output.url.endswith("video.mp4")


def test_mock_provider_covers_image_video_chat_and_costs_nothing() -> None:
    provider = MockProvider()
    images = provider.generate_image(ImageGenerationRequest(prompt="offline", count=2))
    assert len(images.outputs) == 2
    assert all(output.data for output in images.outputs)

    submission = provider.submit_video(VideoGenerationRequest(prompt="offline video"))
    video = provider.poll_video(submission)
    assert video.state == "succeeded" and video.output and video.output.data
    assert provider.complete_chat([{"role": "user", "content": "hello"}]) == "[mock] hello"
    assert estimate_cost("image", "text2img", {"provider": "mock", "n": 10}) == 0.0
    assert estimate_cost("video", "text2video", {"provider": "mock", "duration": 15}) == 0.0
    assert estimate_cost("image", "text2img", {
        "provider": "google", "model": "gemini-3-pro-image", "resolution": "2K"
    }) == 0.134
    assert estimate_cost("image", "edit", {
        "provider": "xai", "model": "grok-imagine-image-2.0",
        "resolution": "2k", "quality": "medium", "images": ["a", "b"],
    }) == 0.10


def test_mock_provider_runs_through_backend_and_creates_artifact() -> None:
    import caelo_core.history_store as history_store
    from caelo_core.genjobs import GenJob
    from caelo_core.state import Backend

    with tempfile.TemporaryDirectory() as directory:
        store = history_store.HistoryStore(Path(directory) / "phase1.db")
        previous = history_store._default_store
        history_store._default_store = store
        try:
            backend = Backend.__new__(Backend)
            backend._provider_instances = {}
            backend.current_project_id = None

            class FakeHistory:
                def get_save_path(self):
                    return directory

                def save_to_history(self, *args, **kwargs):
                    return None

            backend.history = FakeHistory()
            job = GenJob(
                id="mock-1", kind="image", op="text2img",
                params={"provider": "mock", "prompt": "offline", "n": 1,
                        "model": "mock-image"},
                created_at=time.time(), updated_at=time.time(),
            )
            artifact_ids = backend._run_image_job(job, threading.Event())
            artifact = store.get_artifact(artifact_ids[0])
            assert artifact is not None and artifact.type == "image"
            assert Path(artifact.path).is_file()
            assert artifact.meta["provider"] == "mock"
        finally:
            history_store._default_store = previous
            store.close()


def test_error_taxonomy_drives_retry_policy() -> None:
    transient = RuntimeError("service timeout")
    normalized = normalize_provider_error(transient, "xai")
    assert normalized.category is ErrorCategory.TIMEOUT
    assert normalized.retryable is True

    denied = RuntimeError("forbidden")
    denied.response = SimpleNamespace(status_code=403)  # type: ignore[attr-defined]
    normalized_denied = normalize_provider_error(denied, "xai")
    assert normalized_denied.category is ErrorCategory.PERMISSION
    assert normalized_denied.retryable is False


def test_catalog_routes_keep_machine_readable_shape() -> None:
    providers = list_providers()
    assert providers["default"] == "xai"
    assert any(item["id"] == "mock" and item["no_cost"] for item in providers["providers"])

    all_caps = list_capabilities(provider="xai", model=None, media_type="video")
    assert all(item["media_type"] == "video" for item in all_caps["capabilities"])
    one = list_capabilities(
        provider="xai", model="grok-imagine-video-1.5", media_type="video"
    )
    assert one["capability"]["capabilities"]["max_reference_images"] == 3

    backend = SimpleNamespace(
        read_settings=lambda: {},
        list_chat_models=lambda: ["grok-4.6"],
    )
    models = list_models(provider="mock", media_type="image", b=backend)
    assert models["image"]  # stary kontrakt pozostaje dostepny
    assert [item["id"] for item in models["items"]] == ["mock-image"]
