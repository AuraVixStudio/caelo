"""Kontrakt rzeczywistych klas błędów zwracanych przez OpenAI API."""

from __future__ import annotations

import requests

from caelo_core.providers.errors import ErrorCategory, normalize_provider_error


class FakeResponse:
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self._payload = {"error": {"code": code, "message": message}}

    def json(self) -> dict:
        return self._payload


def api_error(status: int, code: str, message: str = "") -> requests.HTTPError:
    error = requests.HTTPError(f"{status} provider error")
    error.response = FakeResponse(status, code, message)  # type: ignore[assignment]
    return error


def test_openai_401_is_auth_and_preserves_safe_machine_code() -> None:
    error = normalize_provider_error(
        api_error(401, "invalid_api_key", "Incorrect API key provided"), "openai"
    )
    assert error.category is ErrorCategory.AUTH
    assert error.code == "invalid_api_key"
    assert error.retryable is False
    assert "Incorrect API key" not in str(error)


def test_openai_unknown_model_is_unsupported_and_not_retried() -> None:
    error = normalize_provider_error(
        api_error(404, "model_not_found", "The requested model does not exist"), "openai"
    )
    assert error.category is ErrorCategory.UNSUPPORTED
    assert error.code == "model_not_found"
    assert error.retryable is False


def test_openai_rate_limit_is_retryable_but_exhausted_quota_is_not() -> None:
    rate = normalize_provider_error(
        api_error(429, "rate_limit_exceeded", "Rate limit reached"), "openai"
    )
    quota = normalize_provider_error(
        api_error(429, "insufficient_quota", "You exceeded your current quota"), "openai"
    )
    assert rate.category is ErrorCategory.RATE_LIMIT
    assert rate.retryable is True
    assert quota.category is ErrorCategory.QUOTA
    assert quota.retryable is False


def test_openai_requests_timeout_is_retryable_even_without_message() -> None:
    error = normalize_provider_error(requests.Timeout(), "openai")
    assert error.category is ErrorCategory.TIMEOUT
    assert error.retryable is True


def test_openai_safety_response_is_not_retried_or_leaked() -> None:
    error = normalize_provider_error(
        api_error(400, "moderation_blocked", "Request blocked by safety policy"), "openai"
    )
    assert error.category is ErrorCategory.SAFETY
    assert error.retryable is False
    assert "Request blocked" not in str(error)
