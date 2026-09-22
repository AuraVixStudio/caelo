"""Konfiguracja Google odseparowana od chronionego legacy `config.py`."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Mapping

from caelo_core.providers.errors import ErrorCategory, ProviderError


_PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{4,61}[a-z0-9]$")
_LOCATION_RE = re.compile(r"^[a-z0-9-]{2,40}$")


@dataclass(frozen=True)
class GoogleConfig:
    auth_mode: str
    project_id: str
    location: str
    video_location: str
    api_key: str

    @property
    def is_vertex(self) -> bool:
        return self.auth_mode == "vertex"

    @classmethod
    def from_settings(cls, settings: Mapping[str, Any]) -> "GoogleConfig":
        raw_mode = str(settings.get("google_auth_mode") or "vertex").strip().lower()
        mode = "ai_studio" if raw_mode in {"ai_studio", "api_key", "aistudio"} else "vertex"
        return cls(
            auth_mode=mode,
            project_id=str(settings.get("google_project_id") or os.getenv("GOOGLE_CLOUD_PROJECT")
                           or os.getenv("GCLOUD_PROJECT") or "").strip(),
            location=str(settings.get("google_location") or "global").strip().lower(),
            video_location=str(settings.get("google_video_location") or "us-central1").strip().lower(),
            api_key=str(settings.get("google_api_key") or os.getenv("GEMINI_API_KEY")
                        or os.getenv("GOOGLE_API_KEY") or "").strip(),
        )

    def validate(self) -> None:
        if self.is_vertex:
            if not self.project_id or not _PROJECT_RE.fullmatch(self.project_id):
                raise ProviderError(
                    "Google Cloud project ID is missing or invalid",
                    provider="google", category=ErrorCategory.INVALID_INPUT,
                )
        elif not self.api_key:
            raise ProviderError(
                "Google AI Studio API key is not configured",
                provider="google", category=ErrorCategory.AUTH,
            )
        for name, value in (("location", self.location), ("video location", self.video_location)):
            if not _LOCATION_RE.fullmatch(value):
                raise ProviderError(
                    f"Google {name} is invalid", provider="google",
                    category=ErrorCategory.INVALID_INPUT,
                )


def sanitize_settings_patch(data: dict[str, Any]) -> dict[str, Any]:
    """Waliduje tylko pola Google; sekret pozostaje jednokierunkowy."""
    out = dict(data)
    if "google_auth_mode" in out:
        mode = str(out["google_auth_mode"]).strip().lower()
        if mode not in {"vertex", "ai_studio"}:
            out.pop("google_auth_mode")
        else:
            out["google_auth_mode"] = mode
    if "google_project_id" in out:
        value = str(out["google_project_id"]).strip()
        if value and not _PROJECT_RE.fullmatch(value):
            out.pop("google_project_id")
        else:
            out["google_project_id"] = value
    for key in ("google_location", "google_video_location"):
        if key in out:
            value = str(out[key]).strip().lower()
            if not _LOCATION_RE.fullmatch(value):
                out.pop(key)
            else:
                out[key] = value
    return out
