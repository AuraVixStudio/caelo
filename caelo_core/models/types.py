"""Typy wpisow neutralnego katalogu dostawcow i modeli."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .capabilities import ModelCapabilities


@dataclass(frozen=True)
class ProviderDescriptor:
    id: str
    label: str
    modalities: tuple[str, ...]
    auth_modes: tuple[str, ...]
    no_cost: bool = False
    status: str = "stable"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModelDescriptor:
    id: str
    provider: str
    label: str
    media_type: str
    capabilities: ModelCapabilities
    status: str = "stable"
    tier: str = "standard"
    is_default: bool = False
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["capabilities"] = self.capabilities.to_dict()
        return data
