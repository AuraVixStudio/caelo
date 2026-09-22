"""Wspólne identyfikatory aktywnych providerów tekstowych Caelo.

To jest jedno runtime'owe źródło prawdy dla tras Chat i runnera Agent. Registry
modeli nadal jest źródłem capabilities; ten moduł określa wyłącznie adaptery,
które są faktycznie zaimplementowane i można bezpiecznie uruchomić.
"""

from __future__ import annotations

from typing import Literal, Optional, TypeAlias

ChatProviderId: TypeAlias = Literal["xai", "google", "openai"]
AgentProviderId: TypeAlias = Literal["xai", "google", "openai"]

ACTIVE_CHAT_PROVIDER_IDS: tuple[ChatProviderId, ...] = ("xai", "google", "openai")
ACTIVE_AGENT_PROVIDER_IDS: tuple[AgentProviderId, ...] = ("xai", "google", "openai")
ACTIVE_PROVIDER_IDS: tuple[str, ...] = ("xai", "google", "openai", "mock")


def normalize_provider_id(value: object, allowed: tuple[str, ...]) -> Optional[str]:
    """Znormalizuj id z granicy transportu; nieznane wartości odrzuć jawnie."""
    provider_id = str(value or "").strip().lower()
    return provider_id if provider_id in allowed else None
