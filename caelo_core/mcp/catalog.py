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
                "env" → ustaw `env[env_key]`;
                "auth" → wstaw jako `Authorization: Bearer <wartość>` (transport
                `http`; token lokalnego endpointu MCP).
`secret: True` → pole hasłowe w UI.

Część wpisów jest UZUPEŁNIANA w `catalog()` o to, co da się wykryć na tej
maszynie (patrz `_sceneagent_bridge_path`) — statyczne dane nie mogą znać
ścieżki, którą wybrał instalator innego programu.
"""

from __future__ import annotations

import copy
import logging
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_HOMEPAGE_SERVERS = "https://github.com/modelcontextprotocol/servers"
_HOMEPAGE_SCENEAGENT = "https://auravixstudio.com"

#: Gdzie instalator SceneAgent MCP zapisuje katalog instalacji, i jak nazywa się
#: most. Czytane, a nie zgadywane: użytkownik mógł zainstalować gdzie indziej.
_SCENEAGENT_REGISTRY_KEY = r"SOFTWARE\SceneAgentMCP"
_SCENEAGENT_BRIDGE_EXE = "SceneAgentMCPBridge.exe"

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
    # Dwa wpisy, bo to dwie edycje jednego produktu i różnią się TRANSPORTEM,
    # a nie ustawieniem: Pro wystawia MCP po stdio przez własny most, Plugin
    # Edition to sam DLL wewnątrz DAZ Studio, słuchający na pętli zwrotnej.
    # Jeden wpis z przełącznikiem kazałby userowi wybrać coś, o czym decyduje to,
    # co kupił.
    {
        "id": "sceneagent-mcp",
        "name": "SceneAgent MCP (DAZ Studio 6)",
        "description": "Read and control a running DAZ Studio 6 scene: build "
                       "scenes, pose figures, render, and undo any of it.",
        "category": "3D",
        "transport": "stdio",
        # Podstawiane przez `_with_sceneagent_detection`: wykryta ścieżka mostu,
        # a gdy produktu nie ma — token `{bridge}` i pole poniżej.
        "command": ["{bridge}"],
        "inputs": [{"key": "bridge", "label": "Path to SceneAgentMCPBridge.exe",
                    "target": "arg",
                    "placeholder": r"C:\Program Files\SceneAgent MCP\SceneAgentMCPBridge.exe",
                    "required": True}],
        "requires": "SceneAgent MCP (Pro), and DAZ Studio 6 running with the bridge enabled",
        "homepage": _HOMEPAGE_SCENEAGENT,
    },
    {
        "id": "sceneagent-mcp-plugin",
        "name": "SceneAgent MCP (Plugin Edition)",
        "description": "The same DAZ Studio 6 scene control, served by the "
                       "plugin itself over loopback HTTP; no extra program runs.",
        "category": "3D",
        "transport": "http",
        "url": "http://127.0.0.1:8772/mcp",
        # Token NIE jest wykrywany automatycznie, choć ścieżkę mostu wykrywamy.
        # Leży w `HKCU\\...\\SceneAgent MCP\\http\\token` jako blob DPAPI, a nasza
        # umowa mówi, że sekrety nie wracają do renderera — wpis katalogu jedzie
        # właśnie tam. Panel SceneAgent ma „Copy MCP client config", które wkłada
        # do schowka JSON z linią `"Authorization": "Bearer <token>"`; resolver
        # przyjmuje wklejone i z prefiksem, i bez.
        "inputs": [{"key": "token",
                    "label": "Access token — SceneAgent pane, Copy MCP client config",
                    "placeholder": "Bearer ...",
                    "target": "auth", "required": True, "secret": True}],
        "requires": "SceneAgent MCP Plugin Edition, with MCP over HTTP started in its pane",
        "homepage": _HOMEPAGE_SCENEAGENT,
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


def _sceneagent_bridge_path() -> Optional[str]:
    """Ścieżka do mostu SceneAgent MCP z rejestru, albo None gdy nie zainstalowany.

    Statyczny katalog nie może zaszyć tej ścieżki — jest per maszyna (instalator
    pozwala wybrać katalog). Bez odczytu wpis wymagałby od usera wklejenia
    ścieżki, czyli przestałby być „one-click" dokładnie dla programu, który tę
    ścieżkę o sobie zapisał.

    Cicho zwraca None wszędzie poza Windows i przy każdym błędzie: brak wpisu to
    normalny stan (produkt niezainstalowany), a nie awaria katalogu.
    """
    if os.name != "nt":
        return None
    try:
        import winreg
    except ImportError:  # pragma: no cover - tylko nie-Windows
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _SCENEAGENT_REGISTRY_KEY) as key:
            location = winreg.QueryValueEx(key, "InstallLocation")[0]
    except OSError:
        return None
    if not location:
        return None
    bridge = Path(str(location)) / _SCENEAGENT_BRIDGE_EXE
    try:
        # Sam wpis w rejestrze nie wystarczy: po odinstalowaniu ręcznym albo po
        # przeniesieniu katalogu klucz potrafi zostać, a komenda wskazywałaby na
        # program, którego nie ma — czyli serwer, który zawsze nie wstaje.
        return str(bridge) if bridge.is_file() else None
    except OSError:
        return None


def _with_sceneagent_detection(entries: list[dict]) -> list[dict]:
    """Uzupełnij wpis Pro o wykrytą ścieżkę mostu (albo zostaw pole do wpisania)."""
    bridge = _sceneagent_bridge_path()
    for entry in entries:
        if entry.get("id") != "sceneagent-mcp":
            continue
        if bridge:
            entry["command"] = [bridge]
            entry.pop("inputs", None)
            entry["requires"] = "SceneAgent MCP (Pro) — detected"
        else:
            entry["command"] = ["{bridge}"]
    return entries


def catalog() -> list[dict]:
    """Kopia kurowanego katalogu (callerzy nie mutują stałej modułu)."""
    return _with_sceneagent_detection(copy.deepcopy(MCP_CATALOG))
