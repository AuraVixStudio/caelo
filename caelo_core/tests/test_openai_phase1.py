"""Faza 1 OpenAI: sejf, registry i bezpłatna diagnostyka połączenia."""

from __future__ import annotations

import pytest

from caelo_core.models.registry import get_model_registry
from caelo_core.providers.errors import ErrorCategory, ProviderError
from caelo_core.providers.openai import OpenAIClient, OpenAIProvider
from caelo_core.runtime_secrets import RuntimeSecrets


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse({"data": [
            {"id": "gpt-5.6-sol"}, {"id": "gpt-5.6-terra"}, {"id": "other-model"},
        ]})


def test_openai_registry_exposes_chat_and_image_models_and_capabilities() -> None:
    registry = get_model_registry()
    provider = registry.provider("openai")
    assert provider is not None
    assert provider.modalities == ("chat", "image")
    assert provider.auth_modes == ("api_key",)
    models = registry.models(provider="openai", media_type="chat")
    assert {model.id for model in models} == {
        "gpt-6-astra", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna",
    }
    assert registry.default_for("openai", "chat").id == "gpt-5.6-terra"
    assert all(model.capabilities.supports_tools for model in models)
    assert all(model.capabilities.supports_streaming for model in models)
    image = registry.default_for("openai", "image")
    assert image is not None and image.id == "gpt-image-2"
    assert image.capabilities.operations == ("text2img", "edit", "variation")


def test_openai_client_discovers_models_with_bearer_and_cache() -> None:
    session = FakeSession()
    client = OpenAIClient(lambda: "sk-test-secret", session=session)
    first = client.list_models()
    second = client.list_models()
    assert first == second == ("gpt-5.6-sol", "gpt-5.6-terra", "other-model")
    assert len(session.calls) == 1
    url, kwargs = session.calls[0]
    assert url == "https://api.openai.com/v1/models"
    assert "sk-test-secret" not in url
    assert kwargs["headers"]["Authorization"] == "Bearer sk-test-secret"
    assert kwargs["timeout"] == 30


def test_openai_provider_validation_intersects_discovery_with_supported_models() -> None:
    provider = OpenAIProvider(lambda: "sk-test")
    provider.client = OpenAIClient(lambda: "sk-test", session=FakeSession())
    result = provider.validate_connection()
    assert result["ok"] is True
    assert result["provider"] == "openai"
    assert result["supported_models"] == ["gpt-5.6-sol", "gpt-5.6-terra"]


def test_openai_missing_key_fails_as_provider_auth_error() -> None:
    client = OpenAIClient(lambda: "", session=FakeSession())
    with pytest.raises(ProviderError) as caught:
        client.list_models()
    assert caught.value.provider == "openai"
    assert caught.value.category == ErrorCategory.AUTH
    assert caught.value.retryable is False


def test_runtime_secret_v1_migrates_to_v2_without_inventing_openai_key() -> None:
    secrets = RuntimeSecrets()
    migrated = secrets.import_snapshot({
        "version": 1,
        "revision": 9,
        "xai_api_key": "x",
        "google_api_key": "g",
        "oauth_tokens": {},
    })
    assert migrated == {
        "version": 2,
        "revision": 9,
        "xai_api_key": "x",
        "google_api_key": "g",
        "openai_api_key": "",
        "oauth_tokens": {},
    }
