"""Czat OpenAI na wspólnym transporcie Responses API."""

from __future__ import annotations

from typing import Any, Callable, Iterable, Optional

from caelo_core.models.openai_models import openai_models
from caelo_core.models.pricing import openai_cost_from_usage
from caelo_core.providers import responses_transport
from caelo_core.providers.base import ChatCompletionResult
from caelo_core.providers.errors import normalize_provider_error

from .client import OPENAI_API_BASE


class OpenAIChatProvider:
    """Polityka OpenAI nad neutralnym transportem HTTP/SSE.

    Historia pozostaje lokalna: każda tura wysyła pełny kontekst i wymusza
    ``store: false``. Modele GPT-5.6 nie otrzymują ``temperature``; reasoning
    jest wysyłany wyłącznie przez neutralne pole ``reasoning.effort``.
    """

    def __init__(self, api_key_provider: Callable[[], str]) -> None:
        self._api_key_provider = api_key_provider

    @staticmethod
    def _default_model() -> str:
        models = openai_models()
        return next((item.id for item in models if item.is_default), models[0].id)

    def stream_chat(
        self,
        messages: Iterable[dict[str, Any]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        reasoning_effort: Optional[str] = None,
        search_grounding: bool = False,
        search_mode: str = "off",
        on_delta: Optional[Callable[[str, str], None]] = None,
        on_tool: Optional[Callable[[dict[str, Any]], None]] = None,
        stop_flag: Optional[Callable[[], bool]] = None,
    ) -> ChatCompletionResult:
        del temperature  # capabilities: GPT-5.6 w Caelo nie przyjmuje tego parametru
        mode = search_mode if search_mode in {"auto", "on", "off"} else "off"
        if search_grounding and mode == "off":
            mode = "auto"
        tools = [{"type": "web_search"}] if mode != "off" else None
        try:
            result = responses_transport.stream_response(
                list(messages),
                model=model or self._default_model(),
                api_key_provider=self._api_key_provider,
                temperature=None,
                reasoning_effort=reasoning_effort,
                tools=tools,
                tool_choice="required" if mode == "on" else None,
                on_delta=on_delta,
                on_tool=on_tool,
                stop_flag=stop_flag,
                base=OPENAI_API_BASE,
                store=False,
            )
        except Exception as exc:  # noqa: BLE001
            raise normalize_provider_error(exc, "openai") from exc
        cost = openai_cost_from_usage(model or self._default_model(), result.get("usage") or {})
        if cost is not None:
            result.setdefault("usage", {})["cost_usd"] = cost
        return ChatCompletionResult(
            text=result["text"],
            citations=tuple(result.get("citations") or ()),
            usage=dict(result.get("usage") or {}),
            tool_calls=int(result.get("tool_calls") or 0),
        )

    def complete_chat(
        self,
        messages: Iterable[dict[str, Any]],
        *,
        model: Optional[str] = None,
        **options: Any,
    ) -> str:
        return self.stream_chat(messages, model=model, **options).text
