"""Minimalny klient OpenAI API używany przez registry i diagnostykę."""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

import requests  # type: ignore

from caelo_core.providers.errors import ErrorCategory, ProviderError, normalize_provider_error


OPENAI_API_BASE = "https://api.openai.com/v1"
MODEL_CACHE_SECONDS = 300.0


class OpenAIClient:
    def __init__(
        self,
        api_key_provider: Callable[[], str],
        *,
        base_url: str = OPENAI_API_BASE,
        session=None,
    ) -> None:
        self._api_key_provider = api_key_provider
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self._lock = threading.RLock()
        self._models: tuple[str, ...] = ()
        self._models_at = 0.0

    def _headers(self) -> dict[str, str]:
        key = self.api_key()
        return {"Authorization": f"Bearer {key}", "Accept": "application/json"}

    def api_key(self) -> str:
        """Zwróć sekret wyłącznie kodowi backendu albo zgłoś jawny błąd auth."""
        key = self._api_key_provider().strip()
        if not key:
            raise ProviderError(
                "OpenAI API key is not configured",
                provider="openai",
                category=ErrorCategory.AUTH,
                retryable=False,
                code="MISSING_API_KEY",
            )
        return key

    def list_models(self, *, force: bool = False) -> tuple[str, ...]:
        now = time.monotonic()
        with self._lock:
            if not force and self._models and now - self._models_at < MODEL_CACHE_SECONDS:
                return self._models
        try:
            response = self.session.get(
                f"{self.base_url}/models", headers=self._headers(), timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
            ids = tuple(sorted({
                str(item.get("id"))
                for item in (payload.get("data") or [])
                if isinstance(item, dict) and item.get("id")
            }))
        except Exception as exc:  # noqa: BLE001
            raise normalize_provider_error(exc, "openai") from exc
        with self._lock:
            self._models = ids
            self._models_at = now
        return ids

    def validate_connection(self, known_models: Optional[set[str]] = None) -> dict:
        available = self.list_models(force=True)
        known = known_models or set()
        supported = sorted(known.intersection(available)) if known else []
        return {
            "ok": True,
            "provider": "openai",
            "available_model_count": len(available),
            "supported_models": supported,
        }
