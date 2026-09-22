"""Adapter xAI dla wspólnego transportu OpenAI Responses.

Polityka dostawcy pozostaje tutaj: domyślny endpoint xAI, źródła web/X oraz
przeliczanie rzeczywistego kosztu z xAI usage ticks. Kod HTTP, parser SSE,
załączniki i pętla function callingu żyją w providers.responses_transport.
"""

from __future__ import annotations

from typing import Callable, List, Optional

import requests  # type: ignore

import config  # type: ignore
from caelo_core.providers import responses_transport as _transport

TIMEOUT_RESPONSES = _transport.TIMEOUT_RESPONSES
to_input = _transport.to_input


def build_search_tools(
    mode: str = "auto",
    sources: Optional[List[str]] = None,
) -> Optional[List[dict]]:
    """Zbuduj narzędzia wyszukiwania właściwe wyłącznie dla xAI."""
    if mode == "off":
        return None
    sources = sources or ["web", "x"]
    tools: List[dict] = []
    if "web" in sources or "news" in sources:
        tools.append({"type": "web_search"})
    if "x" in sources:
        tools.append({"type": "x_search"})
    return tools or None


def stream_response(
    messages: list,
    *,
    model: str,
    api_key_provider: Callable[[], str],
    temperature: Optional[float] = 0.7,
    reasoning_effort: Optional[str] = None,
    tools: Optional[List[dict]] = None,
    tool_choice: Optional[str] = None,
    on_delta: Optional[Callable[[str, str], None]] = None,
    on_tool: Optional[Callable[[dict], None]] = None,
    stop_flag: Optional[Callable[[], bool]] = None,
    base: Optional[str] = None,
    function_tools: Optional[List[dict]] = None,
    tool_handler: Optional[Callable[[str, dict], str]] = None,
    remote_tools: Optional[List[dict]] = None,
    max_tool_iters: int = 8,
) -> dict:
    """Uruchom transport Responses z polityką i kompatybilnością xAI."""
    # Dotychczasowe self-checki podmieniają obiekt requests w tym module.
    # Przekazanie go do transportu zachowuje publiczny seam testowy.
    _transport.requests = requests
    return _transport.stream_response(
        messages,
        model=model,
        api_key_provider=api_key_provider,
        temperature=temperature,
        reasoning_effort=reasoning_effort,
        tools=tools,
        tool_choice=tool_choice,
        on_delta=on_delta,
        on_tool=on_tool,
        stop_flag=stop_flag,
        base=base or config.API_BASE,
        function_tools=function_tools,
        tool_handler=tool_handler,
        remote_tools=remote_tools,
        max_tool_iters=max_tool_iters,
        cost_resolver=config.real_cost_from_usage,
    )
