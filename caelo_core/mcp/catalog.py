"""Kurowany katalog popularnych serwerów MCP (Faza-G / TOP4) — „one-click" instalacja.

To statyczne, kurowane DANE (jak builtin skills/templates): lista znanych serwerów MCP,
które user może dodać jednym kliknięciem. „Install" = `McpManager.add_server(enabled=False)`
(reuse maszynerii M14) — dodanie NIE startuje serwera (**install ≠ autostart**); start to
osobna, jawna, potwierdzana akcja (jak `run_command`). Wpisy są SZABLONAMI: część wymaga
uzupełnienia (`inputs` — ścieżka katalogu / klucz API), które renderer podstawia przed
wysłaniem do `add_server`.

Nazwy pakietów = stan wiedzy I 2026; user weryfikuje przez `homepage` i widzi komendę przed
startem (consent). Komendy `npx -y` są cross-platform (manager owija `npx`/`.cmd` w `cmd /c`
na Windows). Tekst UI po angielsku (konwencja projektu).

`input.target`: "arg" → podstaw wartość w miejsce tokenu `{key}` w `command`;
                "env" → ustaw `env[env_key]`. `secret: True` → pole hasłowe w UI.
"""

from __future__ import annotations

import copy

_HOMEPAGE_SERVERS = "https://github.com/modelcontextprotocol/servers"

MCP_CATALOG: list[dict] = [
    {
        "id": "filesystem",
        "name": "Filesystem",
        "description": "Read and write files within a directory you explicitly allow.",
        "category": "Files",
        "transport": "stdio",
        "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "{path}"],
        "inputs": [{"key": "path", "label": "Allowed directory", "target": "arg",
                    "placeholder": "C:/work", "required": True}],
        "requires": "Node.js (npx)",
        "homepage": _HOMEPAGE_SERVERS,
    },
    {
        "id": "memory",
        "name": "Memory",
        "description": "A persistent knowledge graph the model can store facts in and recall.",
        "category": "Memory",
        "transport": "stdio",
        "command": ["npx", "-y", "@modelcontextprotocol/server-memory"],
        "requires": "Node.js (npx)",
        "homepage": _HOMEPAGE_SERVERS,
    },
    {
        "id": "sequential-thinking",
        "name": "Sequential Thinking",
        "description": "A structured step-by-step reasoning and planning aid.",
        "category": "Reasoning",
        "transport": "stdio",
        "command": ["npx", "-y", "@modelcontextprotocol/server-sequential-thinking"],
        "requires": "Node.js (npx)",
        "homepage": _HOMEPAGE_SERVERS,
    },
    {
        "id": "everything",
        "name": "Everything (demo)",
        "description": "Reference server exercising every MCP feature — handy to verify MCP works.",
        "category": "Demo",
        "transport": "stdio",
        "command": ["npx", "-y", "@modelcontextprotocol/server-everything"],
        "requires": "Node.js (npx)",
        "homepage": _HOMEPAGE_SERVERS,
    },
    {
        "id": "github",
        "name": "GitHub",
        "description": "Search repositories, read files, and manage issues and pull requests.",
        "category": "Development",
        "transport": "stdio",
        "command": ["npx", "-y", "@modelcontextprotocol/server-github"],
        "inputs": [{"key": "token", "label": "GitHub personal access token", "target": "env",
                    "env_key": "GITHUB_PERSONAL_ACCESS_TOKEN", "required": True, "secret": True}],
        "requires": "Node.js (npx)",
        "homepage": _HOMEPAGE_SERVERS,
    },
    {
        "id": "playwright",
        "name": "Playwright (browser)",
        "description": "Drive a real browser — navigate, click, fill forms, snapshot pages.",
        "category": "Browser",
        "transport": "stdio",
        "command": ["npx", "-y", "@playwright/mcp@latest"],
        "requires": "Node.js (npx)",
        "homepage": "https://github.com/microsoft/playwright-mcp",
    },
    {
        "id": "brave-search",
        "name": "Brave Search",
        "description": "Web and local search through the Brave Search API.",
        "category": "Search",
        "transport": "stdio",
        "command": ["npx", "-y", "@modelcontextprotocol/server-brave-search"],
        "inputs": [{"key": "api_key", "label": "Brave Search API key", "target": "env",
                    "env_key": "BRAVE_API_KEY", "required": True, "secret": True}],
        "requires": "Node.js (npx)",
        "homepage": _HOMEPAGE_SERVERS,
    },
]


def catalog() -> list[dict]:
    """Kopia kurowanego katalogu (callerzy nie mutują stałej modułu)."""
    return copy.deepcopy(MCP_CATALOG)
