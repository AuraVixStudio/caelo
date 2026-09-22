"""Testy akceptacyjne Fazy 2: 8 modeli Google, transport, auth i cache plikow."""

from __future__ import annotations

import base64
import json
import tempfile
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from caelo_core.models.pricing import estimate_cost
from caelo_core.models.capabilities import CapabilityError
from caelo_core.models.registry import get_model_registry
from caelo_core.providers import ImageGenerationRequest, VideoGenerationRequest
from caelo_core.providers.google.client import GoogleClient
from caelo_core.providers.google.config import GoogleConfig, sanitize_settings_patch
from caelo_core.providers.google.files import GoogleFileManager, RemoteFileCache
from caelo_core.providers.google.provider import GoogleProvider
from caelo_core.routes.settings import get_settings
from caelo_core.providers.errors import ErrorCategory, ProviderError


PNG = base64.b64encode(b"phase2-image").decode()
MP4 = base64.b64encode(b"phase2-video").decode()
IMAGE_URI = f"data:image/png;base64,{PNG}"
VIDEO_URI = f"data:video/mp4;base64,{MP4}"


class FakeGoogleClient:
    def __init__(self, *, vertex: bool = True) -> None:
        self.vertex = vertex
        self.calls: list[tuple] = []

    def config(self):
        return SimpleNamespace(is_vertex=self.vertex)

    def validate_connection(self):
        return {"ok": True}

    def generate_content(self, model, payload):
        self.calls.append(("image", model, payload))
        return {"candidates": [{"content": {"parts": [
            {"inlineData": {"mimeType": "image/png", "data": PNG}}
        ]}}]}

    def create_interaction(self, payload):
        self.calls.append(("omni-submit", payload))
        return {"id": "interaction-1", "status": "in_progress"}

    def get_interaction(self, interaction_id):
        self.calls.append(("omni-poll", interaction_id))
        return {"id": interaction_id, "status": "completed", "outputs": [
            {"type": "video", "mime_type": "video/mp4", "data": MP4}
        ]}

    def submit_veo(self, model, payload):
        self.calls.append(("veo-submit", model, payload))
        return {"name": "projects/p/locations/us-central1/operations/op-1"}

    def get_veo_operation(self, model, name):
        self.calls.append(("veo-poll", model, name))
        return {"done": True, "response": {"videos": [
            {"mimeType": "video/mp4", "bytesBase64Encoded": MP4}
        ]}}

    def download(self, uri):
        self.calls.append(("download", uri))
        return b"downloaded-video"


@pytest.mark.parametrize("model", [
    "gemini-3.1-flash-image",
    "gemini-3.1-flash-lite-image",
    "gemini-3-pro-image",
    "gemini-2.5-flash-image",
])
def test_all_four_google_image_models_generate_inline_artifacts(model: str) -> None:
    client = FakeGoogleClient()
    provider = GoogleProvider(lambda: {}, client=client)  # type: ignore[arg-type]
    result = provider.generate_image(ImageGenerationRequest(
        prompt="A glass city", model=model, resolution="1k", count=1,
    ))
    assert result.outputs[0].data == b"phase2-image"
    call = client.calls[0]
    assert call[1] == model
    assert call[2]["generationConfig"]["imageConfig"]["imageSize"] == "1K"
    assert call[2]["generationConfig"]["imageConfig"]["personGeneration"] == "ALLOW_ADULT"
    assert call[2]["safetySettings"] == [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "OFF"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "OFF"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "OFF"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "OFF"},
    ]


@pytest.mark.parametrize("model", [
    "gemini-omni-1.1-flash",
    "veo-3.1-generate-preview",
    "veo-3.1-fast-generate-preview",
    "veo-3.1-lite-generate-preview",
])
def test_all_four_google_video_models_submit_poll_and_return_media(model: str) -> None:
    client = FakeGoogleClient()
    provider = GoogleProvider(lambda: {}, client=client)  # type: ignore[arg-type]
    submission = provider.submit_video(VideoGenerationRequest(
        prompt="A slow camera move", model=model, duration=4,
        resolution="720p", aspect_ratio="16:9",
    ))
    status = provider.poll_video(submission)
    assert submission.remote_id
    assert status.state == "succeeded"
    assert status.output and status.output.data == b"phase2-video"
    if model.startswith("veo-"):
        submit_call = next(call for call in client.calls if call[0] == "veo-submit")
        assert submit_call[1].endswith("-001")


def test_nano_banana_roles_thinking_and_search_are_mapped() -> None:
    client = FakeGoogleClient()
    provider = GoogleProvider(lambda: {}, client=client)  # type: ignore[arg-type]
    provider.generate_image(ImageGenerationRequest(
        prompt="Keep the hero", model="gemini-3.1-flash-image", images=(IMAGE_URI,),
        reference_roles=("character",), thinking_level="high", search_grounding=True,
    ))
    payload = client.calls[0][2]
    assert "identity" in payload["contents"][0]["parts"][0]["text"]
    assert payload["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "high"}
    assert payload["tools"] == [{"googleSearch": {}}]


@pytest.mark.parametrize(("response", "expected_code", "expected_detail"), [
    ({"promptFeedback": {"blockReason": "PROHIBITED_CONTENT"}},
     "PROHIBITED_CONTENT", "PROHIBITED_CONTENT"),
    ({"candidates": [{"finishReason": "IMAGE_SAFETY", "safetyRatings": [{
        "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
        "probability": "HIGH",
        "blocked": True,
    }]}]}, "IMAGE_SAFETY", "SEXUALLY_EXPLICIT=HIGH"),
])
def test_google_image_safety_blocks_are_diagnostic_and_never_retried(
    response: dict, expected_code: str, expected_detail: str
) -> None:
    client = FakeGoogleClient()
    client.generate_content = lambda model, payload: response  # type: ignore[method-assign]
    provider = GoogleProvider(lambda: {}, client=client)  # type: ignore[arg-type]

    with pytest.raises(ProviderError) as captured:
        provider.generate_image(ImageGenerationRequest(
            prompt="Adult portrait", model="gemini-3.1-flash-image",
        ))

    error = captured.value
    assert error.category is ErrorCategory.SAFETY
    assert error.retryable is False
    assert error.code == expected_code
    assert expected_detail in str(error)


def test_google_empty_non_safety_response_is_retryable() -> None:
    client = FakeGoogleClient()
    client.generate_content = lambda model, payload: {"candidates": []}  # type: ignore[method-assign]
    provider = GoogleProvider(lambda: {}, client=client)  # type: ignore[arg-type]

    with pytest.raises(ProviderError) as captured:
        provider.generate_image(ImageGenerationRequest(
            prompt="Landscape", model="gemini-3.1-flash-image",
        ))

    assert captured.value.category is ErrorCategory.REMOTE
    assert captured.value.retryable is True
    assert captured.value.code == "NO_IMAGE"


def test_veo_first_last_references_and_extension_payloads() -> None:
    client = FakeGoogleClient()
    provider = GoogleProvider(lambda: {}, client=client)  # type: ignore[arg-type]
    provider.submit_video(VideoGenerationRequest(
        prompt="interpolate", operation="first_last_frame",
        model="veo-3.1-generate-preview", duration=8, resolution="720p",
        aspect_ratio="16:9", image=IMAGE_URI, last_image=IMAGE_URI,
    ))
    payload = client.calls[-1][2]
    assert "image" in payload["instances"][0]
    assert "lastFrame" in payload["parameters"]

    provider.submit_video(VideoGenerationRequest(
        prompt="continue", operation="extend", model="veo-3.1-fast-generate-preview",
        duration=7, resolution="1080p", aspect_ratio="16:9", video=VIDEO_URI,
    ))
    payload = client.calls[-1][2]
    assert payload["parameters"]["resolution"] == "720p"
    assert payload["parameters"]["durationSeconds"] == 7


def test_registry_exposes_exactly_eight_google_media_models_and_guard() -> None:
    registry = get_model_registry()
    models = [m for m in registry.models(provider="google") if m.media_type in {"image", "video"}]
    assert len(models) == 8
    assert len(registry.models(provider="google", media_type="image")) == 4
    assert len(registry.models(provider="google", media_type="video")) == 4
    assert registry.provider("google").auth_modes == ("adc", "api_key")  # type: ignore[union-attr]
    with pytest.raises(Exception):
        registry.validate("google", "video", "extend", {
            "duration": 7, "resolution": "720p", "aspect_ratio": "16:9"
        }, "veo-3.1-lite-generate-preview")


def test_google_image_reference_limits_match_current_model_documentation() -> None:
    registry = get_model_registry()
    flash = registry.find("google", "gemini-3.1-flash-image")
    lite = registry.find("google", "gemini-3.1-flash-lite-image")
    pro = registry.find("google", "gemini-3-pro-image")
    assert flash is not None and lite is not None and pro is not None
    assert flash.capabilities.resolutions == ("0.5k", "1k", "2k", "4k")

    assert (flash.capabilities.max_reference_images,
            flash.capabilities.max_character_reference_images,
            flash.capabilities.max_object_reference_images,
            flash.capabilities.max_style_reference_images) == (14, 4, 10, 0)
    assert (lite.capabilities.max_reference_images,
            lite.capabilities.max_character_reference_images,
            lite.capabilities.max_object_reference_images,
            lite.capabilities.max_style_reference_images) == (14, 0, 14, 0)
    assert (pro.capabilities.max_reference_images,
            pro.capabilities.max_character_reference_images,
            pro.capabilities.max_object_reference_images,
            pro.capabilities.max_style_reference_images) == (14, 5, 6, 3)


def test_google_image_reference_roles_are_enforced_before_generation() -> None:
    registry = get_model_registry()
    image = IMAGE_URI

    with pytest.raises(CapabilityError, match="does not support style"):
        registry.validate("google", "image", "edit", {
            "images": [image], "reference_roles": ["style"]
        }, "gemini-3.1-flash-image")

    registry.validate("google", "image", "edit", {
        "images": [image, image, image], "reference_roles": ["style", "style", "style"]
    }, "gemini-3-pro-image")

    with pytest.raises(CapabilityError, match="Only one starting image"):
        registry.validate("google", "image", "edit", {
            "images": [image, image],
            "reference_roles": ["starting_image", "starting_image"],
        }, "gemini-3-pro-image")


def test_google_config_and_secret_patch_are_safe() -> None:
    vertex = GoogleConfig.from_settings({
        "google_auth_mode": "vertex", "google_project_id": "valid-project-123",
    })
    vertex.validate()
    ai = GoogleConfig.from_settings({"google_auth_mode": "ai_studio", "google_api_key": "secret"})
    ai.validate()
    assert sanitize_settings_patch({"google_project_id": "NOT VALID", "google_location": "global"}) == {
        "google_location": "global"
    }


def test_remote_file_cache_deduplicates_and_expires() -> None:
    cache = RemoteFileCache()
    item = cache.put(b"same", name="files/a", uri="https://files/a", mime_type="video/mp4")
    assert cache.get(b"same") is item
    cache._items[item.sha256] = replace(item, expires_at=0)  # test wygasniecia bez sleep
    assert cache.get(b"same") is None


class FakeResponse:
    def __init__(self, payload, status=200, headers=None):
        self.status_code = status
        self._payload = payload
        self.content = json.dumps(payload).encode()
        self.headers = headers or {}

    def json(self):
        return self._payload


class RecordingSession:
    def __init__(self):
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return FakeResponse({"ok": True})


def test_google_client_uses_vertex_adc_and_ai_studio_endpoints_without_leaking_key() -> None:
    vertex_session = RecordingSession()
    vertex = GoogleClient(lambda: {
        "google_auth_mode": "vertex", "google_project_id": "valid-project-123",
        "google_location": "global", "google_video_location": "us-central1",
    }, session=vertex_session, token_provider=lambda: "adc-token")
    vertex.generate_content("gemini-3.1-flash-image", {"contents": []})
    _, url, kwargs = vertex_session.calls[0]
    assert "/projects/valid-project-123/locations/global/" in url
    assert kwargs["headers"]["Authorization"] == "Bearer adc-token"

    studio_session = RecordingSession()
    studio = GoogleClient(lambda: {
        "google_auth_mode": "ai_studio", "google_api_key": "studio-secret",
    }, session=studio_session)
    studio.generate_content("gemini-3.1-flash-image", {"contents": []})
    _, url, kwargs = studio_session.calls[0]
    assert "generativelanguage.googleapis.com/v1beta/models/" in url
    assert "studio-secret" not in url
    assert kwargs["headers"]["x-goog-api-key"] == "studio-secret"


def test_google_pricing_uses_current_resolution_tiers() -> None:
    assert estimate_cost("video", "text2video", {
        "provider": "google", "model": "veo-3.1-fast-generate-preview",
        "resolution": "1080p", "duration": 8,
    }) == 0.96
    assert estimate_cost("video", "text2video", {
        "provider": "google", "model": "veo-3.1-lite-generate-preview",
        "resolution": "720p", "duration": 8,
    }) == 0.4


def test_ai_studio_file_upload_is_resumable_and_deduplicated() -> None:
    class UploadSession:
        def __init__(self):
            self.calls = []

        def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            if "upload/v1beta/files" in url:
                return FakeResponse({}, headers={"X-Goog-Upload-URL": "https://upload.test/session"})
            return FakeResponse({"file": {"name": "files/a", "uri": "https://files.test/a"}})

    session = UploadSession()
    client = GoogleClient(lambda: {
        "google_auth_mode": "ai_studio", "google_api_key": "secret",
    }, session=session)
    files = GoogleFileManager(client)
    first = files.upload_bytes(b"clip", "video/mp4")
    second = files.upload_bytes(b"clip", "video/mp4")
    assert first is second
    assert len(session.calls) == 2
    assert session.calls[1][2]["headers"]["X-Goog-Upload-Command"] == "upload, finalize"


def test_settings_response_never_returns_google_secret() -> None:
    backend = SimpleNamespace(
        read_settings=lambda: {
            "google_auth_mode": "ai_studio", "google_api_key": "top-secret",
            "google_project_id": "valid-project-123",
        },
        has_api_key=lambda: False,
    )
    response = get_settings(backend)
    assert response["google_has_api_key"] is True
    assert "google_api_key" not in response
    assert "top-secret" not in json.dumps(response)


@pytest.mark.parametrize(("kind", "model"), [
    ("image", "gemini-3.1-flash-image"),
    ("image", "gemini-3.1-flash-lite-image"),
    ("image", "gemini-3-pro-image"),
    ("image", "gemini-2.5-flash-image"),
    ("video", "gemini-omni-1.1-flash"),
    ("video", "veo-3.1-generate-preview"),
    ("video", "veo-3.1-fast-generate-preview"),
    ("video", "veo-3.1-lite-generate-preview"),
])
def test_each_google_model_runs_end_to_end_to_disk_and_gallery(kind: str, model: str) -> None:
    import caelo_core.history_store as history_store
    from caelo_core.genjobs import GenJob
    from caelo_core.state import Backend

    with tempfile.TemporaryDirectory() as directory:
        store = history_store.HistoryStore(Path(directory) / "phase2.db")
        previous = history_store._default_store
        history_store._default_store = store
        try:
            backend = Backend.__new__(Backend)
            backend._provider_instances = {
                "google": GoogleProvider(lambda: {}, client=FakeGoogleClient())  # type: ignore[arg-type]
            }
            backend.current_project_id = None

            class FakeHistory:
                def get_save_path(self):
                    return directory

                def save_to_history(self, *args, **kwargs):
                    return None

            backend.history = FakeHistory()
            params = {
                "provider": "google", "prompt": "phase2 e2e", "model": model,
                "duration": 4, "resolution": "720p" if kind == "video" else "1k",
                "aspect_ratio": "16:9" if kind == "video" else "1:1", "n": 1,
            }
            job = GenJob(id=f"google-{kind}", kind=kind,
                         op="text2video" if kind == "video" else "text2img",
                         params=params, cost=estimate_cost(kind, "text2video" if kind == "video" else "text2img", params),
                         created_at=time.time(), updated_at=time.time())
            artifact_ids = (backend._run_video_job(job, threading.Event()) if kind == "video"
                            else backend._run_image_job(job, threading.Event()))
            artifact = store.get_artifact(artifact_ids[0])
            assert artifact is not None
            assert Path(artifact.path).is_file()
            assert artifact.meta["provider"] == "google"
            assert job.cost > 0
        finally:
            history_store._default_store = previous
            store.close()


# --- Regresja: robocze obrazy „thought" nie mogą trafić do galerii ---------------
# Nano Banana z `thinkingConfig` zwraca w tej samej odpowiedzi podglądy robocze
# oznaczone `thought: true` — ZAWSZE w 1K, niezależnie od `imageConfig.imageSize`.
# Wzięcie pierwszego obrazu dawało wersję roboczą, więc „2K/4K" w UI nic nie zmieniało.

DRAFT = base64.b64encode(b"thought-draft-1k").decode()
FINAL = base64.b64encode(b"final-render-4k").decode()


class ThinkingImageClient(FakeGoogleClient):
    def generate_content(self, model, payload):
        self.calls.append(("generateContent", model, payload))
        return {"candidates": [{"content": {"parts": [
            {"thought": True, "inlineData": {"mimeType": "image/png", "data": DRAFT}},
            {"text": "Rendering the final image."},
            {"inlineData": {"mimeType": "image/png", "data": FINAL}},
        ]}}]}


def test_thought_preview_is_skipped_and_final_render_is_kept() -> None:
    client = ThinkingImageClient()
    provider = GoogleProvider(lambda: {}, client=client)  # type: ignore[arg-type]
    result = provider.generate_image(ImageGenerationRequest(
        prompt="A glass city", model="gemini-3.1-flash-image",
        resolution="4k", thinking_level="medium", count=1,
    ))
    assert result.outputs[0].data == b"final-render-4k"
    assert client.calls[0][2]["generationConfig"]["imageConfig"]["imageSize"] == "4K"


def test_last_image_wins_when_several_are_returned() -> None:
    """Nawet bez flagi `thought` finalny render jest OSTATNI w odpowiedzi."""

    class MultiImageClient(FakeGoogleClient):
        def generate_content(self, model, payload):
            self.calls.append(("generateContent", model, payload))
            return {"candidates": [{"content": {"parts": [
                {"inlineData": {"mimeType": "image/png", "data": DRAFT}},
                {"inlineData": {"mimeType": "image/png", "data": FINAL}},
            ]}}]}

    provider = GoogleProvider(lambda: {}, client=MultiImageClient())  # type: ignore[arg-type]
    result = provider.generate_image(ImageGenerationRequest(
        prompt="A glass city", model="gemini-3-pro-image", resolution="2k", count=1,
    ))
    assert result.outputs[0].data == b"final-render-4k"


# --- Domyślny model czatu może pochodzić od dowolnego dostawcy -------------------
# Ustawienia → General wybierają model z całego katalogu, więc obok `chat_model`
# musi jechać `chat_provider` — inaczej Chat wróciłby do xAI mimo wyboru Gemini.

def test_chat_provider_round_trips_and_rejects_unknown_provider() -> None:
    from caelo_core.routes.settings import SettingsPatch, put_settings

    stored: dict = {}
    backend = SimpleNamespace(
        read_settings=lambda: stored,
        update_settings=stored.update,
        has_api_key=lambda: False,
        set_api_key=lambda value: None,
        set_google_api_key=lambda value: None,
        set_openai_api_key=lambda value: None,
    )

    put_settings(SettingsPatch(chat_model="gemini-3.7-flash", chat_provider="google"), backend)
    assert stored["chat_provider"] == "google"
    assert get_settings(backend)["chat_provider"] == "google"

    # Nieznany dostawca jest pomijany, a nie zapisywany — plik ustawień zostaje spójny.
    put_settings(SettingsPatch(chat_provider="wymyslony"), backend)
    assert stored["chat_provider"] == "google"


def test_chat_provider_defaults_to_xai_for_settings_without_it() -> None:
    backend = SimpleNamespace(read_settings=lambda: {}, has_api_key=lambda: False)
    assert get_settings(backend)["chat_provider"] == "xai"


# --- Omni: id katalogowe vs id na drucie (LIVE 2026-09-01) ----------------------
# Vertex odrzucal `gemini-omni-1.1-flash` bledem 400 "Unsupported model interaction";
# przechodzi dopiero `gemini-omni-1.1-flash-preview`. AI Studio uzywa nazwy bez sufiksu,
# wiec — dokladnie jak przy Veo — mapujemy TYLKO na drucie, a katalog/cennik/artefakty
# trzymaja jedno id.

def test_omni_uses_the_preview_id_on_vertex_but_keeps_the_catalog_id() -> None:
    client = FakeGoogleClient(vertex=True)
    provider = GoogleProvider(lambda: {}, client=client)  # type: ignore[arg-type]
    submission = provider.submit_video(VideoGenerationRequest(
        prompt="A red balloon", model="gemini-omni-1.1-flash", duration=3,
        resolution="360p", aspect_ratio="16:9",
    ))
    payload = next(call for call in client.calls if call[0] == "omni-submit")[1]
    assert payload["model"] == "gemini-omni-1.1-flash-preview"
    # Koszt i artefakty musza widziec id z katalogu, inaczej cennik przestaje trafiac.
    assert submission.model == "gemini-omni-1.1-flash"
    assert submission.metadata["wire_model"] == "gemini-omni-1.1-flash-preview"
    assert estimate_cost("video", "text2video", {
        "provider": "google", "model": submission.model, "resolution": "360p", "duration": 3,
    }) > 0


def test_omni_keeps_the_bare_id_on_ai_studio() -> None:
    client = FakeGoogleClient(vertex=False)
    provider = GoogleProvider(lambda: {}, client=client)  # type: ignore[arg-type]
    provider.submit_video(VideoGenerationRequest(
        prompt="A red balloon", model="gemini-omni-1.1-flash", duration=3,
        resolution="360p", aspect_ratio="16:9",
    ))
    payload = next(call for call in client.calls if call[0] == "omni-submit")[1]
    assert payload["model"] == "gemini-omni-1.1-flash"
