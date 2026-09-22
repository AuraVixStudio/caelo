"""Faza 2 OpenAI: kontrakt Responses API dla Chat."""

from __future__ import annotations

import json

import pytest
import requests

from caelo_core.providers import responses_transport
from caelo_core.providers.errors import ErrorCategory, ProviderError
from caelo_core.providers.openai.chat import OpenAIChatProvider


class FakeStreamResponse:
    status_code = 200

    def __init__(self, events: list[dict]) -> None:
        self._events = events
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def close(self) -> None:
        self.closed = True

    def raise_for_status(self) -> None:
        return None

    def iter_lines(self, decode_unicode=False):
        del decode_unicode
        for event in self._events:
            yield ("data: " + json.dumps(event, ensure_ascii=False)).encode("utf-8")
        yield b"data: [DONE]"


def test_openai_chat_streams_utf8_usage_citations_and_private_payload(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []
    response = FakeStreamResponse([
        {"type": "response.output_text.delta", "delta": "Zażółć "},
        {"type": "response.output_text.delta", "delta": "gęślą"},
        {"type": "response.completed", "response": {
            "usage": {"input_tokens": 7, "output_tokens": 2, "total_tokens": 9},
            "output": [{"type": "message", "content": [{
                "type": "output_text", "text": "Zażółć gęślą",
                "annotations": [{"type": "url_citation", "url": "https://example.test",
                                 "title": "Example"}],
            }]}],
        }},
    ])

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return response

    monkeypatch.setattr(responses_transport.requests, "post", fake_post)
    deltas: list[tuple[str, str]] = []
    provider = OpenAIChatProvider(lambda: "sk-openai-test")
    result = provider.stream_chat(
        [{"role": "user", "content": "Napisz pangram"}],
        model="gpt-5.6-terra",
        temperature=0.99,
        reasoning_effort="high",
        search_mode="on",
        on_delta=lambda delta, full: deltas.append((delta, full)),
    )

    assert result.text == "Zażółć gęślą"
    assert deltas[-1] == ("gęślą", "Zażółć gęślą")
    assert result.usage["total_tokens"] == 9
    assert result.usage["cost_usd"] == 0.000038
    assert result.citations == ({
        "url": "https://example.test", "title": "Example",
    },)
    url, kwargs = calls[0]
    assert url == "https://api.openai.com/v1/responses"
    assert kwargs["headers"]["Authorization"] == "Bearer sk-openai-test"
    payload = kwargs["json"]
    assert payload["store"] is False
    assert "temperature" not in payload
    assert payload["reasoning"] == {"effort": "high"}
    assert payload["tools"] == [{"type": "web_search"}]
    assert payload["tool_choice"] == "required"
    assert response.closed is True


def test_openai_chat_omits_search_tool_when_disabled(monkeypatch) -> None:
    captured = {}

    def fake_post(_url, **kwargs):
        captured.update(kwargs["json"])
        return FakeStreamResponse([{
            "type": "response.completed",
            "response": {"output": [{"type": "message", "content": [
                {"type": "output_text", "text": "ok"},
            ]}]},
        }])

    monkeypatch.setattr(responses_transport.requests, "post", fake_post)
    result = OpenAIChatProvider(lambda: "sk-test").stream_chat(
        [{"role": "user", "content": "hello"}], search_mode="off",
    )
    assert result.text == "ok"
    assert "tools" not in captured
    assert captured["store"] is False


def test_openai_chat_normalizes_auth_failure(monkeypatch) -> None:
    class Unauthorized(FakeStreamResponse):
        status_code = 401

        def raise_for_status(self) -> None:
            error = requests.HTTPError("401 unauthorized")
            error.response = self  # type: ignore[assignment]
            raise error

    monkeypatch.setattr(
        responses_transport.requests, "post", lambda *_args, **_kwargs: Unauthorized([]),
    )
    with pytest.raises(ProviderError) as caught:
        OpenAIChatProvider(lambda: "bad-key").stream_chat([
            {"role": "user", "content": "hello"},
        ])
    assert caught.value.provider == "openai"
    assert caught.value.category is ErrorCategory.AUTH
    assert caught.value.retryable is False
