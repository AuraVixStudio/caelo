"""Minimalny klient REST Google: ADC/Vertex i AI Studio bez ciezkiego SDK GenAI."""

from __future__ import annotations

import time
import json as jsonlib
from typing import Any, Callable, Iterator, Mapping, Optional
from urllib.parse import quote

import requests

from caelo_core.providers.errors import ErrorCategory, ProviderError, normalize_provider_error

from .config import GoogleConfig


VERTEX_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


class GoogleClient:
    def __init__(self, settings: Callable[[], Mapping[str, Any]], *,
                 session: Optional[Any] = None,
                 token_provider: Optional[Callable[[], str]] = None) -> None:
        self._settings = settings
        self._session = session or requests.Session()
        self._token_provider = token_provider
        self._credentials: Any = None

    def config(self) -> GoogleConfig:
        config = GoogleConfig.from_settings(self._settings())
        config.validate()
        return config

    def _access_token(self) -> str:
        if self._token_provider is not None:
            return self._token_provider()
        try:
            import google.auth  # type: ignore
            from google.auth.transport.requests import Request  # type: ignore
        except ImportError as exc:
            raise ProviderError(
                "Google ADC support is not installed. Install google-auth and sign in with gcloud auth application-default login.",
                provider="google", category=ErrorCategory.AUTH, cause=exc,
            ) from exc
        if self._credentials is None:
            self._credentials, _ = google.auth.default(scopes=[VERTEX_SCOPE])
        if not getattr(self._credentials, "valid", False):
            self._credentials.refresh(Request())
        token = getattr(self._credentials, "token", None)
        if not token:
            raise ProviderError("Google ADC did not return an access token", provider="google",
                                category=ErrorCategory.AUTH)
        return str(token)

    def _headers(self, config: GoogleConfig, extra: Optional[dict[str, str]] = None) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if config.is_vertex:
            headers["Authorization"] = f"Bearer {self._access_token()}"
        else:
            headers["x-goog-api-key"] = config.api_key
        headers.update(extra or {})
        return headers

    @staticmethod
    def _error_message(payload: Any, fallback: str) -> tuple[str, Optional[str]]:
        node = payload[0] if isinstance(payload, list) and payload else payload
        error = node.get("error") if isinstance(node, dict) else None
        if isinstance(error, dict):
            reason = None
            details = error.get("details") or []
            for detail in details:
                if isinstance(detail, dict) and detail.get("reason"):
                    reason = str(detail["reason"])
                    break
            return str(error.get("message") or fallback), reason or str(error.get("status") or "") or None
        return fallback, None

    def request(self, method: str, url: str, *, json: Any = None, data: Any = None,
                headers: Optional[dict[str, str]] = None, retry_poll: bool = False,
                timeout: int = 120) -> Any:
        config = self.config()
        attempts = 3 if retry_poll else 1
        last: Optional[BaseException] = None
        for attempt in range(attempts):
            try:
                response = self._session.request(
                    method, url, json=json, data=data,
                    headers=self._headers(config, headers), timeout=timeout,
                )
                if 200 <= int(response.status_code) < 300:
                    if int(response.status_code) == 204 or not getattr(response, "content", b""):
                        return {}
                    return response.json()
                try:
                    payload = response.json()
                except Exception:
                    payload = None
                message, code = self._error_message(payload, f"Google API returned HTTP {response.status_code}")
                error = RuntimeError(message)
                error.response = response  # type: ignore[attr-defined]
                error.code = code  # type: ignore[attr-defined]
                normalized = normalize_provider_error(error, "google")
                if retry_poll and normalized.retryable and attempt + 1 < attempts:
                    time.sleep(0.25 * (2 ** attempt))
                    continue
                raise normalized
            except ProviderError:
                raise
            except Exception as exc:
                last = exc
                normalized = normalize_provider_error(exc, "google")
                if retry_poll and normalized.retryable and attempt + 1 < attempts:
                    time.sleep(0.25 * (2 ** attempt))
                    continue
                raise normalized from exc
        raise normalize_provider_error(last or RuntimeError("Google request failed"), "google")

    def generate_content(self, model: str, payload: dict[str, Any]) -> dict[str, Any]:
        c = self.config()
        if c.is_vertex:
            url = ("https://aiplatform.googleapis.com/v1beta1/projects/"
                   f"{quote(c.project_id)}/locations/{quote(c.location)}/publishers/google/models/"
                   f"{quote(model)}:generateContent")
        else:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{quote(model)}:generateContent"
        return self.request("POST", url, json=payload)

    def stream_generate_content(
        self, model: str, payload: dict[str, Any]
    ) -> Iterator[dict[str, Any]]:
        """Stream ``GenerateContentResponse`` z oficjalnego endpointu SSE.

        Klucz AI Studio pozostaje w nagłówku, a Vertex korzysta z tego samego ADC
        co obraz i wideo. Parser akceptuje zarówno ramki ``data:`` jak i pojedyncze
        obiekty JSON, ponieważ implementacje testowe/proxy nie zawsze zachowują
        dokładne formatowanie SSE.
        """
        c = self.config()
        if c.is_vertex:
            url = ("https://aiplatform.googleapis.com/v1beta1/projects/"
                   f"{quote(c.project_id)}/locations/{quote(c.location)}/publishers/google/models/"
                   f"{quote(model)}:streamGenerateContent?alt=sse")
        else:
            url = ("https://generativelanguage.googleapis.com/v1beta/models/"
                   f"{quote(model)}:streamGenerateContent?alt=sse")

        try:
            response = self._session.request(
                "POST", url, json=payload, headers=self._headers(c),
                timeout=(20, 300), stream=True,
            )
            if not 200 <= int(response.status_code) < 300:
                try:
                    try:
                        error_payload = response.json()
                    except Exception:
                        error_payload = None
                    message, code = self._error_message(
                        error_payload, f"Google API returned HTTP {response.status_code}"
                    )
                    error = RuntimeError(message)
                    error.response = response  # type: ignore[attr-defined]
                    error.code = code  # type: ignore[attr-defined]
                    raise normalize_provider_error(error, "google")
                finally:
                    close = getattr(response, "close", None)
                    if callable(close):
                        close()

            data_lines: list[str] = []

            def decode_event() -> Optional[dict[str, Any]]:
                if not data_lines:
                    return None
                raw = "\n".join(data_lines).strip()
                data_lines.clear()
                if not raw or raw == "[DONE]":
                    return None
                parsed = jsonlib.loads(raw)
                return parsed if isinstance(parsed, dict) else None

            try:
                for raw_line in response.iter_lines(decode_unicode=False):
                    line = (raw_line.decode("utf-8") if isinstance(raw_line, bytes)
                            else str(raw_line or ""))
                    if not line:
                        event = decode_event()
                        if event is not None:
                            yield event
                        continue
                    if line.startswith(":") or line.startswith("event:"):
                        continue
                    if line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
                    elif line.lstrip().startswith("{"):
                        data_lines.append(line.strip())
                event = decode_event()
                if event is not None:
                    yield event
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
        except ProviderError:
            raise
        except Exception as exc:
            raise normalize_provider_error(exc, "google") from exc

    def create_interaction(self, payload: dict[str, Any]) -> dict[str, Any]:
        c = self.config()
        if c.is_vertex:
            url = ("https://aiplatform.googleapis.com/v1beta1/projects/"
                   f"{quote(c.project_id)}/locations/{quote(c.location)}/interactions")
        else:
            url = "https://generativelanguage.googleapis.com/v1beta/interactions"
        return self.request("POST", url, json=payload)

    def get_interaction(self, interaction_id: str) -> dict[str, Any]:
        c = self.config()
        if c.is_vertex:
            url = ("https://aiplatform.googleapis.com/v1beta1/projects/"
                   f"{quote(c.project_id)}/locations/{quote(c.location)}/interactions/{quote(interaction_id)}")
        else:
            url = f"https://generativelanguage.googleapis.com/v1beta/interactions/{quote(interaction_id)}"
        return self.request("GET", url, retry_poll=True)

    def submit_veo(self, model: str, payload: dict[str, Any]) -> dict[str, Any]:
        c = self.config()
        if c.is_vertex:
            url = (f"https://{c.video_location}-aiplatform.googleapis.com/v1/projects/"
                   f"{quote(c.project_id)}/locations/{quote(c.video_location)}/publishers/google/models/"
                   f"{quote(model)}:predictLongRunning")
        else:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{quote(model)}:predictLongRunning"
        return self.request("POST", url, json=payload)

    def get_veo_operation(self, model: str, operation_name: str) -> dict[str, Any]:
        c = self.config()
        if c.is_vertex:
            url = (f"https://{c.video_location}-aiplatform.googleapis.com/v1/projects/"
                   f"{quote(c.project_id)}/locations/{quote(c.video_location)}/publishers/google/models/"
                   f"{quote(model)}:fetchPredictOperation")
            return self.request("POST", url, json={"operationName": operation_name}, retry_poll=True)
        name = operation_name[1:] if operation_name.startswith("/") else operation_name
        url = f"https://generativelanguage.googleapis.com/v1beta/{name}"
        return self.request("GET", url, retry_poll=True)

    def download(self, uri: str) -> bytes:
        c = self.config()
        response = self._session.request("GET", uri, headers=self._headers(c), timeout=180)
        if not 200 <= int(response.status_code) < 300:
            error = RuntimeError(f"Google media download returned HTTP {response.status_code}")
            error.response = response  # type: ignore[attr-defined]
            raise normalize_provider_error(error, "google")
        return bytes(response.content)

    def validate_connection(self) -> dict[str, Any]:
        c = self.config()
        if c.is_vertex:
            self._access_token()
            return {"ok": True, "auth_mode": "adc", "project_id": c.project_id,
                    "location": c.location, "message": "Google Cloud ADC is available."}
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-image"
        self.request("GET", url, retry_poll=True)
        return {"ok": True, "auth_mode": "api_key", "message": "Google AI Studio key is valid."}
