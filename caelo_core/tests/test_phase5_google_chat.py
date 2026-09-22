"""Testy kontraktowe Fazy 5: streaming Google w module Chat."""

from __future__ import annotations

import base64
import json
import pytest

from caelo_core.models.registry import get_model_registry
from caelo_core.providers.errors import ErrorCategory, ProviderError
from caelo_core.providers.google.chat import GoogleChatProvider, build_google_chat_payload
from caelo_core.providers.google.client import GoogleClient


IMAGE = "data:image/png;base64," + base64.b64encode(b"image").decode()
PDF = "data:application/pdf;base64," + base64.b64encode(b"%PDF-test").decode()


class FakeChatClient:
    def __init__(self, chunks):
        self.chunks = chunks
        self.calls = []

    def stream_generate_content(self, model, payload):
        self.calls.append((model, payload))
        yield from self.chunks


def test_payload_maps_system_history_image_pdf_and_gemini3_thinking() -> None:
    payload = build_google_chat_payload([
        {"role": "system", "content": "Be concise."},
        {"role": "user", "content": [
            {"type": "text", "text": "Describe these files"},
            {"type": "image_url", "image_url": {"url": IMAGE}},
            {"type": "document", "document": {
                "data": PDF, "mime": "application/pdf", "name": "brief.pdf",
            }},
        ]},
        {"role": "assistant", "content": "Earlier response"},
        {"role": "user", "content": "Continue"},
    ], model="gemini-3.6-flash", temperature=0.9, reasoning_effort="high")

    assert payload["systemInstruction"]["parts"] == [{"text": "Be concise."}]
    assert [item["role"] for item in payload["contents"]] == ["user", "model", "user"]
    assert payload["contents"][0]["parts"][1]["inlineData"]["mimeType"] == "image/png"
    assert payload["contents"][0]["parts"][2]["inlineData"]["mimeType"] == "application/pdf"
    assert payload["generationConfig"] == {"thinkingConfig": {"thinkingLevel": "high"}}
    assert all(item["threshold"] == "OFF" for item in payload["safetySettings"])


def test_payload_keeps_temperature_only_for_gemini25() -> None:
    payload = build_google_chat_payload(
        [{"role": "user", "content": "Hello"}],
        model="gemini-2.5-flash", temperature=0.35,
    )
    assert payload["generationConfig"] == {"temperature": 0.35}


def test_google_chat_streams_text_usage_and_citations() -> None:
    client = FakeChatClient([
        {"candidates": [{"content": {"parts": [{"text": "Zażółć "}]}}]},
        {"candidates": [{"content": {"parts": [
            {"thought": True, "text": "hidden"}, {"text": "gęślą"}
        ]}, "groundingMetadata": {"groundingChunks": [
            {"web": {"uri": "https://example.test", "title": "Example"}}
        ]}}], "usageMetadata": {
            "promptTokenCount": 12, "candidatesTokenCount": 4, "totalTokenCount": 16,
        }},
    ])
    provider = GoogleChatProvider(client)  # type: ignore[arg-type]
    deltas = []
    result = provider.stream_chat(
        [{"role": "user", "content": "Test"}], model="gemini-3.6-flash",
        on_delta=lambda delta, full: deltas.append((delta, full)),
    )

    assert result.text == "Zażółć gęślą"
    assert deltas[-1] == ("gęślą", "Zażółć gęślą")
    assert result.usage == {"input_tokens": 12, "output_tokens": 4, "total_tokens": 16}
    assert result.citations == ({"url": "https://example.test", "title": "Example"},)


def test_google_chat_reports_safety_block_without_retry() -> None:
    provider = GoogleChatProvider(FakeChatClient([
        {"promptFeedback": {"blockReason": "PROHIBITED_CONTENT"}}
    ]))  # type: ignore[arg-type]
    with pytest.raises(ProviderError) as captured:
        provider.stream_chat([{"role": "user", "content": "test"}])
    assert captured.value.category is ErrorCategory.SAFETY
    assert captured.value.retryable is False
    assert captured.value.code == "PROHIBITED_CONTENT"


class StreamResponse:
    content = b"stream"

    def __init__(self, lines, status_code=200, error_payload=None):
        self.lines = lines
        self.status_code = status_code
        self.error_payload = error_payload
        self.closed = False

    def iter_lines(self, decode_unicode=False):
        yield from self.lines

    def close(self):
        self.closed = True

    def json(self):
        return self.error_payload


class StreamSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.response


def test_google_client_stream_uses_vertex_adc_sse_and_utf8() -> None:
    response = StreamResponse([
        ('data: ' + json.dumps({"candidates": [{"content": {"parts": [
            {"text": "żółw"}
        ]}}]}, ensure_ascii=False)).encode("utf-8"),
        b"",
    ])
    session = StreamSession(response)
    client = GoogleClient(lambda: {
        "google_auth_mode": "vertex", "google_project_id": "valid-project-123",
        "google_location": "global", "google_video_location": "us-central1",
    }, session=session, token_provider=lambda: "adc-token")

    chunks = list(client.stream_generate_content("gemini-3.6-flash", {"contents": []}))
    assert chunks[0]["candidates"][0]["content"]["parts"][0]["text"] == "żółw"
    _, url, kwargs = session.calls[0]
    assert url.endswith(":streamGenerateContent?alt=sse")
    assert "/projects/valid-project-123/locations/global/" in url
    assert kwargs["headers"]["Authorization"] == "Bearer adc-token"
    assert kwargs["stream"] is True
    assert response.closed is True


def test_google_client_closes_failed_stream_response() -> None:
    response = StreamResponse([], status_code=401, error_payload={
        "error": {"message": "Invalid credentials", "status": "UNAUTHENTICATED"}
    })
    client = GoogleClient(lambda: {
        "google_auth_mode": "ai_studio", "google_api_key": "secret-key",
    }, session=StreamSession(response))

    with pytest.raises(ProviderError):
        list(client.stream_generate_content("gemini-3.6-flash", {"contents": []}))
    assert response.closed is True


def test_registry_exposes_google_chat_models_and_capabilities() -> None:
    registry = get_model_registry()
    provider = registry.provider("google")
    models = registry.models(provider="google", media_type="chat")
    assert provider is not None and "chat" in provider.modalities
    assert [model.id for model in models] == [
        "gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash",
        "gemini-3.1-pro-preview",
        "gemini-3.5-flash-lite", "gemini-3.1-flash-lite",
        "gemini-2.5-pro", "gemini-2.5-flash",
    ]
    assert models[0].is_default is True
    assert models[0].capabilities.supports_streaming is True
    assert models[0].capabilities.thinking_levels == ("low", "medium", "high")


def test_google_chat_rejects_office_document_with_clear_message() -> None:
    office = "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,QQ=="
    with pytest.raises(ValueError, match="PDF or text"):
        build_google_chat_payload([{"role": "user", "content": [{
            "type": "document", "document": {"data": office, "mime":
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "name": "x.docx"},
        }]}], model="gemini-3.6-flash")
