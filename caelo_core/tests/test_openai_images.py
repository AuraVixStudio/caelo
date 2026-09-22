"""OpenAI Images API: payloady, media, błędy i walidacja modelu."""

from __future__ import annotations

import base64
import tempfile
import threading
import time
from pathlib import Path

import pytest
import requests

from caelo_core.models.registry import get_model_registry
from caelo_core.providers import ImageGenerationRequest
from caelo_core.providers.errors import ErrorCategory, ProviderError
from caelo_core.providers.openai import OpenAIClient, OpenAIImageProvider, OpenAIProvider
from caelo_core.routes.genjobs import ImageJobReq


IMAGE_BYTES = b"openai-image"
IMAGE_URI = "data:image/png;base64," + base64.b64encode(b"reference").decode()


class FakeResponse:
    def __init__(self, payload: dict, *, status: int = 200, headers: dict | None = None) -> None:
        self._payload = payload
        self.status_code = status
        self.headers = headers or {}

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            error = requests.HTTPError(f"{self.status_code} response")
            error.response = self  # type: ignore[assignment]
            raise error


class RecordingSession:
    def __init__(self, responses: list[FakeResponse] | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.responses = responses or [FakeResponse({
            "data": [{"b64_json": base64.b64encode(IMAGE_BYTES).decode()}],
            "usage": {"input_tokens": 5, "output_tokens": 10},
        }, headers={"x-request-id": "req-image"})]

    def post(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def provider_with(session: RecordingSession) -> OpenAIImageProvider:
    return OpenAIImageProvider(OpenAIClient(lambda: "sk-test", session=session))


def test_openai_generate_uses_json_and_decodes_base64() -> None:
    session = RecordingSession()
    result = provider_with(session).generate_image(ImageGenerationRequest(
        prompt="A glass city", model="gpt-image-2", count=2,
        resolution="2048x1152", quality="high", output_format="webp",
        output_compression=80, background="opaque", moderation="low",
    ))

    assert result.outputs[0].data == IMAGE_BYTES
    assert result.outputs[0].mime_type == "image/webp"
    assert result.outputs[0].extension == ".webp"
    assert result.metadata["request_id"] == "req-image"
    url, kwargs = session.calls[0]
    assert url.endswith("/images/generations")
    assert kwargs["json"] == {
        "model": "gpt-image-2", "prompt": "A glass city", "n": 2,
        "size": "2048x1152", "quality": "high", "output_format": "webp",
        "moderation": "low", "background": "opaque", "output_compression": 80,
    }
    assert kwargs["headers"]["Authorization"] == "Bearer sk-test"
    assert kwargs["timeout"] == 180


def test_openai_edit_uses_multipart_images_and_reference_guidance() -> None:
    session = RecordingSession()
    provider_with(session).generate_image(ImageGenerationRequest(
        prompt="Keep the subject", operation="edit", model="gpt-image-2",
        images=(IMAGE_URI, IMAGE_URI), reference_roles=("character", "style"),
        resolution="1024x1536", output_format="png",
    ))

    url, kwargs = session.calls[0]
    assert url.endswith("/images/edits")
    assert [part[0] for part in kwargs["files"]] == ["image[]", "image[]"]
    assert kwargs["files"][0][1][2] == "image/png"
    assert "preserve character identity" in kwargs["data"]["prompt"]
    assert "visual style references" in kwargs["data"]["prompt"]
    assert kwargs["data"]["moderation"] == "low"


def test_openai_moderation_block_is_specific_and_not_retryable() -> None:
    session = RecordingSession([FakeResponse({"error": {
        "type": "image_generation_user_error", "code": "moderation_blocked",
        "moderation_details": {"moderation_stage": "input", "categories": ["sexual"]},
    }}, status=400)])

    with pytest.raises(ProviderError) as caught:
        provider_with(session).generate_image(ImageGenerationRequest(prompt="blocked"))

    assert caught.value.category is ErrorCategory.SAFETY
    assert caught.value.retryable is False
    assert caught.value.code == "moderation_blocked"
    assert "input" in str(caught.value)


def test_openai_provider_facade_exposes_image_generation() -> None:
    session = RecordingSession()
    provider = OpenAIProvider(lambda: "sk-test")
    provider.client = OpenAIClient(lambda: "sk-test", session=session)
    provider.images = OpenAIImageProvider(provider.client)
    result = provider.generate_image(ImageGenerationRequest(prompt="portrait"))
    assert result.outputs[0].data == IMAGE_BYTES


def test_openai_registry_and_request_allow_multi_image_edits() -> None:
    registry = get_model_registry()
    model = registry.find("openai", "gpt-image-2")
    assert model is not None
    assert model.capabilities.quality_levels == ("low", "medium", "high", "auto")
    assert model.capabilities.output_formats == ("png", "jpeg", "webp")
    assert model.capabilities.moderation_levels == ("low", "auto")
    registry.validate("openai", "image", "edit", {
        "images": [IMAGE_URI] * 4, "reference_roles": ["general"] * 4,
        "resolution": "1024x1024", "quality": "medium",
        "output_format": "png", "background": "auto", "moderation": "low",
    }, "gpt-image-2")
    request = ImageJobReq(
        provider="openai", op="edit", prompt="combine", model="gpt-image-2",
        images=[IMAGE_URI] * 4, reference_roles=["general"] * 4,
        resolution="1024x1024", quality="high", output_format="png",
        background="transparent", moderation="low",
    )
    assert len(request.images) == 4


def test_openai_transparent_jpeg_is_rejected_before_queueing() -> None:
    with pytest.raises(ValueError, match="transparent background"):
        ImageJobReq(
            provider="openai", prompt="portrait", output_format="jpeg",
            background="transparent",
        )


def test_openai_image_runs_through_queue_storage_and_gallery() -> None:
    import caelo_core.history_store as history_store
    from caelo_core.genjobs import GenJob
    from caelo_core.state import Backend

    with tempfile.TemporaryDirectory() as directory:
        store = history_store.HistoryStore(Path(directory) / "openai-images.db")
        previous = history_store._default_store
        history_store._default_store = store
        try:
            backend = Backend.__new__(Backend)
            client = OpenAIClient(lambda: "sk-test", session=RecordingSession())
            provider = OpenAIProvider(lambda: "sk-test")
            provider.client = client
            provider.images = OpenAIImageProvider(client)
            backend._provider_instances = {"openai": provider}
            backend.current_project_id = None

            class FakeHistory:
                def get_save_path(self):
                    return directory

                def save_to_history(self, *args, **kwargs):
                    return None

            backend.history = FakeHistory()
            params = {
                "provider": "openai", "prompt": "queue image", "model": "gpt-image-2",
                "resolution": "1024x1024", "n": 1, "quality": "low",
                "output_format": "png", "moderation": "low",
            }
            job = GenJob(
                id="openai-image", kind="image", op="text2img", params=params,
                cost=0.0, created_at=time.time(), updated_at=time.time(),
            )
            artifact_ids = backend._run_image_job(job, threading.Event())
            assert job.remote_metadata["usage"]["output_tokens"] == 10
            artifact = store.get_artifact(artifact_ids[0])
            assert artifact is not None
            assert Path(artifact.path).is_file()
            assert artifact.meta["provider"] == "openai"
            assert artifact.meta["model"] == "gpt-image-2"
        finally:
            history_store._default_store = previous
            store.close()
