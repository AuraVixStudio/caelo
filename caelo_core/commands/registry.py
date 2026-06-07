"""Rejestr komend slash (M14-B4): wbudowane + użytkownika.

Źródła: stałe wbudowane (`/plan /review /commit /test /mcp`) + `caelo_commands.json`
(użytkownika) + katalog `DATA_DIR/commands/*.md` (frontmatter + body=szablon).
Komenda to deklaratywny rekord — wykonanie (wstawienie szablonu, tryb, akcja) robi
renderer (F3). `expand(name, input)` podstawia `{input}` (i `{args}`) — używane też
po stronie serwera w selfcheckach.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Optional

import config  # type: ignore

from caelo_core.markdown_meta import parse_frontmatter

log = logging.getLogger(__name__)

_NAME_RX = re.compile(r"^[a-zA-Z0-9_-]{1,40}$")

# Wbudowane komendy. `target`: chat|agent|both. `mode`: opcjonalny tryb agenta
# (ask/accept-edits/plan/bypass). `action`: opcjonalna akcja klienta (np. open_mcp).
BUILTIN_COMMANDS: list[dict] = [
    {"name": "plan", "target": "agent", "mode": "plan",
     "description": "Investigate read-only, then propose a step-by-step plan (no changes yet).",
     "template": ("Investigate the codebase using read-only tools, then produce a clear, "
                  "numbered, step-by-step plan for the following task. Do NOT modify anything "
                  "until I approve the plan:\n\n{input}")},
    {"name": "review", "target": "both",
     "description": "Review the current changes (or pasted code) for bugs and clarity.",
     "template": ("Review the following (or the current working changes) for correctness, "
                  "bugs, edge cases and clarity. List concrete, actionable issues:\n\n{input}")},
    {"name": "commit", "target": "agent",
     "description": "Stage changes and propose a git commit (runs git through approval).",
     "template": ("Stage the current changes and create a git commit with a concise, "
                  "conventional message that describes them. Show me the message first. {input}")},
    {"name": "test", "target": "agent",
     "description": "Run the project's tests and report failures.",
     "template": ("Run the project's test suite and report the results concisely. If a failure "
                  "is trivial to fix, fix it and re-run. {input}")},
    {"name": "mcp", "target": "chat", "action": "open_mcp",
     "description": "Open the MCP servers manager / list connected MCP tools.",
     "template": "List the connected MCP servers and the tools they expose. {input}"},
    {"name": "explain", "target": "both",
     "description": "Explain how the given code, file or area works.",
     "template": ("Explain how the following code / file / area works. Start with the big "
                  "picture, then the important parts, with concrete file:line references:\n\n{input}")},
    {"name": "fix", "target": "agent",
     "description": "Find and fix the described bug (reproduce → root cause → fix → verify).",
     "template": ("Fix the bug described below. Reproduce it, find the root cause (not the "
                  "symptom), apply the smallest correct fix, then verify and add a test that "
                  "would have caught it:\n\n{input}")},
    {"name": "refactor", "target": "agent",
     "description": "Refactor the given code/area without changing behavior.",
     "template": ("Refactor the following code/area for clarity and structure WITHOUT changing "
                  "behavior. Work in small steps and verify (tests/type-check) after each:\n\n{input}")},
    {"name": "document", "target": "agent",
     "description": "Add or improve docstrings/comments and update docs for the given code.",
     "template": ("Add or improve docstrings and comments for the following code/area, and update "
                  "any affected docs. Explain *why*, not just *what*; match the existing style:\n\n{input}")},
    {"name": "optimize", "target": "agent",
     "description": "Improve the performance of the given code/area, keeping behavior identical.",
     "template": ("Improve the performance of the following code/area. Measure or reason about the "
                  "hot path first, keep behavior identical, and verify nothing regressed:\n\n{input}")},
]


def _normalize(cmd: dict, *, builtin: bool = False) -> Optional[dict]:
    name = (cmd.get("name") or "").strip().lstrip("/")
    if not _NAME_RX.match(name):
        return None
    out = {
        "name": name,
        "description": cmd.get("description") or "",
        "template": cmd.get("template") or "",
        "target": (cmd.get("target") or "both").lower(),
        "builtin": builtin,
    }
    if out["target"] not in ("chat", "agent", "both"):
        out["target"] = "both"
    if cmd.get("mode"):
        out["mode"] = cmd["mode"]
    if cmd.get("action"):
        out["action"] = cmd["action"]
    return out


class CommandRegistry:
    def __init__(self, config_path: Optional[Path] = None,
                 commands_dir: Optional[Path] = None) -> None:
        self._path = config_path or config.COMMANDS_FILE
        self._dir = Path(commands_dir) if commands_dir else (config.DATA_DIR / "commands")
        self._lock = threading.RLock()

    # --- ładowanie ---
    def _user_from_json(self) -> list[dict]:
        data = config.load_json_or_backup(self._path, {}) or {}
        cmds = data.get("commands") if isinstance(data, dict) else None
        out = []
        for c in cmds or []:
            n = _normalize(c) if isinstance(c, dict) else None
            if n:
                out.append(n)
        return out

    def _user_from_dir(self) -> list[dict]:
        out = []
        try:
            if not self._dir.is_dir():
                return out
            for p in sorted(self._dir.glob("*.md")):
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                meta, body = parse_frontmatter(text)
                cmd = {
                    "name": meta.get("name") or p.stem,
                    "description": meta.get("description") or "",
                    "template": body or meta.get("template") or "",
                    "target": meta.get("target") or "both",
                    "mode": meta.get("mode"),
                    "action": meta.get("action"),
                }
                n = _normalize(cmd)
                if n:
                    out.append(n)
        except Exception:  # noqa: BLE001
            log.warning("Failed to scan commands dir", exc_info=True)
        return out

    def list_commands(self) -> list[dict]:
        """Wbudowane + użytkownika (JSON + katalog). Użytkownik NADPISUJE wbudowaną
        komendę o tej samej nazwie (override). Posortowane po nazwie."""
        with self._lock:
            by_name: dict[str, dict] = {}
            for c in BUILTIN_COMMANDS:
                n = _normalize(c, builtin=True)
                if n:
                    by_name[n["name"]] = n
            for c in self._user_from_dir() + self._user_from_json():
                by_name[c["name"]] = c  # JSON wygrywa z katalogiem; oba nadpisują builtin
        return sorted(by_name.values(), key=lambda c: c["name"])

    def get(self, name: str) -> Optional[dict]:
        name = (name or "").lstrip("/")
        for c in self.list_commands():
            if c["name"] == name:
                return c
        return None

    def expand(self, name: str, input_text: str = "") -> str:
        """Rozwiń szablon komendy. `{input}`/`{args}` → tekst usera; brak komendy →
        sam tekst (graceful). Nadmiarowe `{input}` bez tekstu zwija puste."""
        cmd = self.get(name)
        if cmd is None:
            return input_text or ""
        tmpl = cmd.get("template") or ""
        text = (input_text or "").strip()
        out = tmpl.replace("{input}", text).replace("{args}", text)
        return out.strip()

    # --- zarządzanie komendami użytkownika (JSON) ---
    def add_command(self, cmd: dict) -> dict:
        n = _normalize(cmd)
        if n is None:
            raise ValueError("command name must match [a-zA-Z0-9_-]{1,40}")
        if not n["template"]:
            raise ValueError("command requires a non-empty template")
        with self._lock:
            existing = [c for c in self._user_from_json() if c["name"] != n["name"]]
            existing.append(n)
            self._save(existing)
        return n

    def remove_command(self, name: str) -> bool:
        name = (name or "").lstrip("/")
        with self._lock:
            existing = self._user_from_json()
            kept = [c for c in existing if c["name"] != name]
            if len(kept) == len(existing):
                return False
            self._save(kept)
        return True

    def _save(self, commands: list[dict]) -> None:
        # Zapisuj tylko pola użytkownika (bez 'builtin').
        clean = [{k: v for k, v in c.items() if k != "builtin"} for c in commands]
        try:
            config.atomic_write_text(self._path,
                                     json.dumps({"commands": clean}, indent=2, ensure_ascii=False))
        except Exception:  # noqa: BLE001
            log.warning("Failed to save %s", getattr(self._path, "name", self._path), exc_info=True)
