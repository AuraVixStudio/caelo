"""Normalizacja bledow dostawcow i jedna polityka ponawiania."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional


class ErrorCategory(str, Enum):
    AUTH = "auth"
    PERMISSION = "permission"
    INVALID_INPUT = "invalid_input"
    UNSUPPORTED = "unsupported"
    RATE_LIMIT = "rate_limit"
    QUOTA = "quota"
    SAFETY = "safety"
    NETWORK = "network"
    REMOTE = "remote"
    TIMEOUT = "timeout"
    FILESYSTEM = "filesystem"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class ProviderError(RuntimeError):
    """Bezpieczny, ustrukturyzowany blad wspolny dla wszystkich adapterow."""

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        category: ErrorCategory = ErrorCategory.UNKNOWN,
        retryable: bool = False,
        code: Optional[str] = None,
        status_code: Optional[int] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.category = category
        self.retryable = bool(retryable)
        self.code = code
        self.status_code = status_code
        self.__cause__ = cause

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "category": self.category.value,
            "code": self.code,
            "message": str(self),
            "retryable": self.retryable,
        }


_RETRYABLE_NETWORK_CODES = {
    "ECONNRESET", "ETIMEDOUT", "ECONNREFUSED", "EAI_AGAIN", "ENOTFOUND", "EPIPE",
}


def normalize_provider_error(error: BaseException, provider: str) -> ProviderError:
    """Mapuje wyjatek SDK/HTTP bez ujawniania surowej odpowiedzi rendererowi."""
    if isinstance(error, ProviderError):
        return error

    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    raw_code = getattr(error, "code", None)
    response_message = ""
    if response is not None:
        try:
            payload = response.json()
            details = payload.get("error", payload) if isinstance(payload, dict) else {}
            if isinstance(details, dict):
                raw_code = raw_code or details.get("code") or details.get("type")
                response_message = str(details.get("message") or "")
        except Exception:  # noqa: BLE001 - odpowiedz moze nie byc JSON-em
            pass
    code = str(raw_code) if raw_code is not None else None
    raw_message = str(error or "")
    # Treść odpowiedzi służy wyłącznie do klasyfikacji. Renderer nadal otrzymuje
    # kontrolowany komunikat ProviderError, nigdy surowe body dostawcy.
    lower = f"{raw_message} {response_message} {code or ''}".lower()

    if isinstance(error, ValueError):
        return ProviderError(raw_message or "Invalid provider request", provider=provider,
                             category=ErrorCategory.INVALID_INPUT, retryable=False,
                             cause=error)

    if code and code.upper() in _RETRYABLE_NETWORK_CODES:
        return ProviderError("Network problem while contacting the provider", provider=provider,
                             category=ErrorCategory.NETWORK, retryable=True, code=code,
                             cause=error)
    if "safety" in lower or "policy" in lower or "prohibited" in lower or "blocked" in lower:
        return ProviderError("Generation was blocked by the provider safety policy",
                             provider=provider, category=ErrorCategory.SAFETY,
                             code=code, status_code=status, cause=error)
    if status == 401 or "invalid api key" in lower or "api key not valid" in lower:
        return ProviderError("Provider authentication failed", provider=provider,
                             category=ErrorCategory.AUTH, code=code,
                             status_code=status, cause=error)
    if status == 403:
        return ProviderError("Provider denied access to this operation", provider=provider,
                             category=ErrorCategory.PERMISSION, code=code,
                             status_code=status, cause=error)
    if status == 429:
        exhausted = any(word in lower for word in ("quota", "billing", "resource_exhausted", "free tier"))
        return ProviderError(
            "Provider quota is exhausted" if exhausted else "Provider rate limit reached",
            provider=provider,
            category=ErrorCategory.QUOTA if exhausted else ErrorCategory.RATE_LIMIT,
            retryable=not exhausted,
            code="QUOTA_EXCEEDED" if exhausted else "429",
            status_code=status,
            cause=error,
        )
    if status in (400, 422):
        return ProviderError("Provider rejected the request", provider=provider,
                             category=ErrorCategory.INVALID_INPUT, code=code,
                             status_code=status, cause=error)
    if status == 404:
        return ProviderError("Provider does not support the requested resource",
                             provider=provider, category=ErrorCategory.UNSUPPORTED,
                             code=code, status_code=status, cause=error)
    if status in (500, 502, 503, 504):
        return ProviderError("Provider is temporarily unavailable", provider=provider,
                             category=ErrorCategory.REMOTE, retryable=True,
                             status_code=status, cause=error)
    error_type = type(error).__name__.lower()
    if "timeout" in error_type or isinstance(error, TimeoutError) \
            or "timeout" in lower or "timed out" in lower:
        return ProviderError("Provider request timed out", provider=provider,
                             category=ErrorCategory.TIMEOUT, retryable=True,
                             status_code=status, cause=error)
    if any(word in lower for word in ("connection", "socket", "fetch failed")):
        return ProviderError("Network problem while contacting the provider", provider=provider,
                             category=ErrorCategory.NETWORK, retryable=True,
                             status_code=status, cause=error)
    return ProviderError("Unexpected provider error", provider=provider,
                         category=ErrorCategory.UNKNOWN, status_code=status, cause=error)


def is_retryable(error: BaseException, provider: str = "unknown") -> bool:
    """Jedyna decyzja retry dla providerow; kolejka fazy 3 uzyje jej do backoffu."""
    return normalize_provider_error(error, provider).retryable
