"""Klient MCP (Model Context Protocol) sidecara — M14-B1/B2.

Cienka, **synchroniczna** warstwa nad transportem stdio (newline-delimited
JSON-RPC 2.0) — świadoma decyzja (jak `responses_client` wobec SDK OpenAI):
pasuje do modelu wątków-workerów sidecara, zero nowych zależności, w pełni
testowalna offline mock-serwerem. Transport jest abstrakcyjny (`McpTransport`),
więc Streamable HTTP / native remote MCP (B3) mogą dojść później bez ruszania
reszty.

Bezpieczeństwo (jak `run_command`): podproces serwera startuje ze **scrubbed env**
(bez `GROK_CORE_TOKEN`/`XAI_API_KEY`/sekretów) i jest **tree-killowany** przy
zamknięciu. Dodanie/start serwera wymaga jawnej zgody w UI (gate jak run_command).
"""

from grok_core.mcp.client import (
    McpClient,
    McpError,
    StdioTransport,
)
from grok_core.mcp.manager import McpManager, McpServer

__all__ = [
    "McpClient",
    "McpError",
    "StdioTransport",
    "McpManager",
    "McpServer",
]
