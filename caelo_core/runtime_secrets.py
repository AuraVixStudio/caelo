"""Sekrety runtime przekazane z sejfu Electron ``safeStorage``.

Ten moduł niczego nie zapisuje na dysku. Dane żyją wyłącznie w pamięci procesu
sidecara i są synchronizowane z procesem głównym przez osobny, uwierzytelniony
kanał. Migawka jest wersjonowana, aby odświeżony token OAuth nie został
nadpisany starszą kopią.
"""

from __future__ import annotations

import threading
from copy import deepcopy
from typing import Any, Mapping


SCHEMA_VERSION = 2
SUPPORTED_SCHEMA_VERSIONS = (1, SCHEMA_VERSION)
MAX_SECRET_CHARS = 64 * 1024


def _secret(value: Any) -> str:
    text = value if isinstance(value, str) else ""
    if len(text) > MAX_SECRET_CHARS:
        raise ValueError("Secret value is too large")
    return text


def _tokens(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    # OAuth payload is JSON-compatible and small. Reject pathological input before
    # it can become a long-lived in-memory object.
    result = deepcopy(dict(value))
    if len(repr(result)) > MAX_SECRET_CHARS * 2:
        raise ValueError("OAuth token payload is too large")
    return result


class RuntimeSecrets:
    """Thread-safe in-memory secret snapshot with monotonic revision."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._revision = 0
        self._xai_api_key = ""
        self._google_api_key = ""
        self._openai_api_key = ""
        self._oauth_tokens: dict[str, Any] = {}

    def import_snapshot(self, data: Mapping[str, Any]) -> dict[str, Any]:
        if int(data.get("version") or 0) not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError("Unsupported secret snapshot version")
        revision = int(data.get("revision") or 0)
        if revision < 0:
            raise ValueError("Invalid secret snapshot revision")
        with self._lock:
            self._revision = revision
            self._xai_api_key = _secret(data.get("xai_api_key"))
            self._google_api_key = _secret(data.get("google_api_key"))
            self._openai_api_key = _secret(data.get("openai_api_key"))
            self._oauth_tokens = _tokens(data.get("oauth_tokens"))
            return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "version": SCHEMA_VERSION,
                "revision": self._revision,
                "xai_api_key": self._xai_api_key,
                "google_api_key": self._google_api_key,
                "openai_api_key": self._openai_api_key,
                "oauth_tokens": deepcopy(self._oauth_tokens),
            }

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    def xai_api_key(self) -> str:
        with self._lock:
            return self._xai_api_key

    def google_api_key(self) -> str:
        with self._lock:
            return self._google_api_key

    def openai_api_key(self) -> str:
        with self._lock:
            return self._openai_api_key

    def oauth_tokens(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._oauth_tokens)

    def set_xai_api_key(self, value: str) -> None:
        with self._lock:
            value = _secret(value).strip()
            if value != self._xai_api_key:
                self._xai_api_key = value
                self._revision += 1

    def set_google_api_key(self, value: str) -> None:
        with self._lock:
            value = _secret(value).strip()
            if value != self._google_api_key:
                self._google_api_key = value
                self._revision += 1

    def set_openai_api_key(self, value: str) -> None:
        with self._lock:
            value = _secret(value).strip()
            if value != self._openai_api_key:
                self._openai_api_key = value
                self._revision += 1

    def set_oauth_tokens(self, value: Mapping[str, Any]) -> None:
        tokens = _tokens(value)
        with self._lock:
            if tokens != self._oauth_tokens:
                self._oauth_tokens = tokens
                self._revision += 1
