"""Komendy (slash commands) — M14-B4.

Komenda = szablon promptu + opcjonalne metadane (tryb agenta, cel chat/agent,
akcja klienta). Działa w czacie i agencie: renderer wstawia rozwinięty szablon do
composera, opcjonalnie stosując `mode` (np. `/plan` → tryb planowania) lub `action`
(np. `/mcp` → otwórz menedżera MCP). „Akcja przez bramkę" (np. `/commit`) realizuje
się przez agenta, który wykonuje git przez `run_command` (gate jak zwykle).
"""

from caelo_core.commands.registry import BUILTIN_COMMANDS, CommandRegistry

__all__ = ["CommandRegistry", "BUILTIN_COMMANDS"]
