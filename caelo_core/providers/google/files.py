"""Pliki Google i cache deduplikujacy po SHA-256 (persistencja dopiero w Fazie 3)."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from typing import Optional

from caelo_core.providers.errors import ErrorCategory, ProviderError, normalize_provider_error

from .client import GoogleClient


@dataclass(frozen=True)
class RemoteFile:
    sha256: str
    name: str
    uri: str
    mime_type: str
    expires_at: float


class RemoteFileCache:
    def __init__(self, repository=None) -> None:
        self._items: dict[str, RemoteFile] = {}
        self._lock = threading.RLock()
        self._repository = repository

    def get(self, data: bytes) -> Optional[RemoteFile]:
        digest = hashlib.sha256(data).hexdigest()
        if self._repository is not None:
            row = self._repository.get(digest, "google")
            if row:
                return RemoteFile(digest, row["remote_name"], row["uri"], row["mime"], row["expires_at"])
        with self._lock:
            item = self._items.get(digest)
            if item and item.expires_at > time.time():
                return item
            self._items.pop(digest, None)
            return None

    def put(self, data: bytes, *, name: str, uri: str, mime_type: str,
            ttl_seconds: int = 47 * 60 * 60) -> RemoteFile:
        item = RemoteFile(hashlib.sha256(data).hexdigest(), name, uri, mime_type,
                          time.time() + max(1, ttl_seconds))
        with self._lock:
            self._items[item.sha256] = item
        if self._repository is not None:
            self._repository.put(sha256=item.sha256, provider="google",
                                 remote_name=item.name, uri=item.uri,
                                 mime=item.mime_type, expires_at=item.expires_at)
        return item


class GoogleFileManager:
    """Resumable upload Gemini Files API z deduplikacja lokalnych bajtow."""

    def __init__(self, client: GoogleClient, cache: Optional[RemoteFileCache] = None) -> None:
        self.client = client
        self.cache = cache or RemoteFileCache()

    def upload_bytes(self, data: bytes, mime_type: str, display_name: str = "caelo-input") -> RemoteFile:
        cached = self.cache.get(data)
        if cached:
            return cached
        config = self.client.config()
        if config.is_vertex:
            raise ProviderError(
                "Vertex inputs use inline bytes; Gemini Files upload is only available in AI Studio mode",
                provider="google", category=ErrorCategory.UNSUPPORTED,
            )
        start_headers = self.client._headers(config, {  # noqa: SLF001 - wspolny transport
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(len(data)),
            "X-Goog-Upload-Header-Content-Type": mime_type,
        })
        try:
            start = self.client._session.request(  # noqa: SLF001
                "POST", "https://generativelanguage.googleapis.com/upload/v1beta/files",
                headers=start_headers,
                data=json.dumps({"file": {"display_name": display_name}}).encode(),
                timeout=60,
            )
            if not 200 <= int(start.status_code) < 300:
                error = RuntimeError(f"Google file upload start returned HTTP {start.status_code}")
                error.response = start  # type: ignore[attr-defined]
                raise error
            upload_url = start.headers.get("X-Goog-Upload-URL") or start.headers.get("x-goog-upload-url")
            if not upload_url:
                raise RuntimeError("Google file upload did not return an upload URL")
            finish = self.client._session.request(  # noqa: SLF001
                "POST", upload_url, data=data,
                headers=self.client._headers(config, {
                    "Content-Type": mime_type,
                    "X-Goog-Upload-Offset": "0",
                    "X-Goog-Upload-Command": "upload, finalize",
                }), timeout=180,
            )
            if not 200 <= int(finish.status_code) < 300:
                error = RuntimeError(f"Google file upload returned HTTP {finish.status_code}")
                error.response = finish  # type: ignore[attr-defined]
                raise error
            payload = finish.json()
            file = payload.get("file", payload) if isinstance(payload, dict) else {}
            name = str(file.get("name") or "")
            uri = str(file.get("uri") or file.get("fileUri") or "")
            if not name or not uri:
                raise RuntimeError("Google file upload completed without file metadata")
            return self.cache.put(data, name=name, uri=uri, mime_type=mime_type)
        except ProviderError:
            raise
        except Exception as exc:
            raise normalize_provider_error(exc, "google") from exc
