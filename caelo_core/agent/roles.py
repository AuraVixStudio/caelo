"""Role subagentów + limity zespołu (M17-B2/B5/F4).

Rola = persona subagenta: opis, **zawężony zestaw narzędzi plikowych**, zakres
narzędzi MCP (`none`/`readonly`/`all`), flaga `worktree` (czy rola mutuje i musi
pracować w izolowanej kopii workspace), opcjonalny model (tiering kosztów — wciąż
„tylko Grok", różne warianty) i tryb bramki dla pod-sesji.

Wbudowane role (PLAN_M17 §0): researcher / reviewer = READONLY (bez worktree);
implementer = mutujące w worktree; tester = `run_command` w worktree. Użytkownik
może je nadpisać/dodać (`caelo_subagents.json`, atomowo + `load_json_or_backup`).

Bezpieczeństwo (B5): zakres roli NIGDY nie jest szerszy niż rodzica — egzekwowane
przez przecięcie z `parent_tools` w `effective_tools()`. `mcp:'all'` wciąż przechodzi
przez bramkę dla narzędzi mutujących (jak w agencie), więc to nie eskalacja.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import config  # type: ignore

from caelo_core.agent.permissions import MUTATING, READONLY

log = logging.getLogger(__name__)

# Kanoniczny zbiór narzędzi plikowych agenta (do walidacji zakresu ról).
ALL_FILE_TOOLS = sorted(READONLY | MUTATING)
MCP_SCOPES = ("none", "readonly", "all")

# Wbudowane role — `tools` to dozwolone narzędzia PLIKOWE; `mcp` to zakres MCP.
# `worktree:true` ⇒ rola mutuje i pracuje w izolowanej kopii workspace (scalanie = B4).
BUILTIN_ROLES: list[dict] = [
    {
        "id": "researcher",
        "label": "Researcher",
        "description": "Investigates the codebase read-only and reports findings.",
        "tools": ["read_file", "list_dir", "glob", "grep"],
        "mcp": "readonly",
        "worktree": False,
        "model": "",
        "prompt": (
            "You are a RESEARCH subagent. Investigate the workspace using only the "
            "read-only tools (read_file/list_dir/glob/grep). Do NOT attempt to modify "
            "anything. When done, reply with a concise, structured findings summary "
            "(facts, file paths, line references) that the orchestrator can act on."
        ),
        "builtin": True,
    },
    {
        "id": "reviewer",
        "label": "Reviewer",
        "description": "Reviews code read-only for bugs, risks and quality.",
        "tools": ["read_file", "list_dir", "glob", "grep"],
        "mcp": "readonly",
        "worktree": False,
        "model": "",
        "prompt": (
            "You are a CODE REVIEW subagent. Read the relevant files (read-only tools "
            "only) and review for correctness bugs, security issues and quality. Do NOT "
            "modify anything. Reply with a prioritized list of findings, each with a "
            "file:line reference and a short rationale."
        ),
        "builtin": True,
    },
    {
        "id": "implementer",
        "label": "Implementer",
        "description": "Makes code changes in an isolated worktree (reviewed at merge).",
        "tools": ["read_file", "list_dir", "glob", "grep", "write_file", "edit_file"],
        "mcp": "all",
        "worktree": True,
        "model": "",
        "prompt": (
            "You are an IMPLEMENTER subagent working in an ISOLATED COPY of the workspace. "
            "Make the requested code changes with write_file/edit_file. Keep changes "
            "minimal and focused. Your edits are NOT applied to the real workspace until "
            "the user reviews and merges them, so finish the task fully. Reply with a short "
            "summary of what you changed and why."
        ),
        "builtin": True,
    },
    {
        "id": "tester",
        "label": "Tester",
        "description": "Runs tests/build commands in an isolated worktree.",
        "tools": ["read_file", "list_dir", "glob", "grep", "run_command"],
        "mcp": "all",
        "worktree": True,
        "model": "",
        "prompt": (
            "You are a TESTER subagent working in an ISOLATED COPY of the workspace. Run "
            "the relevant tests or build commands with run_command (one program per call; "
            "no shell operators) and report results. Reply with a concise summary: what you "
            "ran, pass/fail, and any actionable failures."
        ),
        "builtin": True,
    },
]

# Twarde limity zespołu (B5) — anty fork-bomba / wyczerpanie zasobów / koszt.
DEFAULT_LIMITS: dict = {
    "max_parallel": 3,       # ilu subagentów naraz (cap równoległości)
    "max_depth": 1,          # subagent NIE deleguje (brak narzędzia delegate → wymuszone)
    "timeout_s": 300,        # wall-clock per subagent
    "max_subagents": 8,      # twardy cap subagentów na jeden przebieg delegate()
    "max_total_turns": 32,   # budżet: łączna liczba tur LLM w całym przebiegu zespołu
    "max_iters": 16,         # górny limit iteracji pojedynczego subagenta
}

# Granice rozsądku dla limitów (walidacja zapisu z UI).
_LIMIT_BOUNDS = {
    "max_parallel": (1, 8),
    "max_depth": (1, 1),         # M17: głębia = 1 (twardo; głębsze drzewa = przyszłość)
    "timeout_s": (10, 3600),
    "max_subagents": (1, 32),
    "max_total_turns": (1, 200),
    "max_iters": (1, 50),
}


def _clean_role(cfg: dict) -> Optional[dict]:
    """Zwaliduj/oczyść jeden wpis roli z configu. None, gdy bezużyteczny."""
    rid = str(cfg.get("id") or "").strip()
    if not rid:
        return None
    tools = [t for t in (cfg.get("tools") or []) if t in ALL_FILE_TOOLS]
    mcp = cfg.get("mcp") if cfg.get("mcp") in MCP_SCOPES else "readonly"
    return {
        "id": rid,
        "label": str(cfg.get("label") or rid),
        "description": str(cfg.get("description") or ""),
        "tools": tools,
        "mcp": mcp,
        "worktree": bool(cfg.get("worktree", False)),
        "model": str(cfg.get("model") or ""),
        "prompt": str(cfg.get("prompt") or ""),
        "builtin": bool(cfg.get("builtin", False)),
    }


def effective_tools(role: dict, parent_tools: set[str]) -> list[str]:
    """Narzędzia plikowe roli PRZECIĘTE z narzędziami rodzica (B5: brak eskalacji —
    subagent nigdy nie dostaje narzędzia, którego rodzic nie ma)."""
    return sorted(set(role.get("tools") or []) & set(parent_tools))


def role_is_mutating(role: dict) -> bool:
    """Czy rola może mutować (ma narzędzie mutujące lub `mcp:'all'` lub worktree)."""
    if any(t in MUTATING for t in (role.get("tools") or [])):
        return True
    if role.get("mcp") == "all":
        return True
    return bool(role.get("worktree"))


class RoleRegistry:
    """Role + limity zespołu, utrwalane w `caelo_subagents.json` (atomowo).

    Wbudowane role są zawsze dostępne; użytkownik może je nadpisać (po `id`) lub
    dodać własne. Limity scalane z domyślnymi (brakujące pola → default)."""

    def __init__(self, path=None) -> None:
        self._path = path or config.SUBAGENTS_FILE
        self._user_roles: dict[str, dict] = {}
        self._limits: dict = dict(DEFAULT_LIMITS)
        self._load()

    # --- trwałość ---
    def _load(self) -> None:
        data = config.load_json_or_backup(self._path, {}) or {}
        for cfg in (data.get("roles") if isinstance(data, dict) else None) or []:
            clean = _clean_role(cfg) if isinstance(cfg, dict) else None
            if clean:
                clean["builtin"] = False  # cokolwiek w pliku usera jest „user"
                self._user_roles[clean["id"]] = clean
        limits = data.get("limits") if isinstance(data, dict) else None
        if isinstance(limits, dict):
            self._limits = self._merge_limits(limits)

    def _save(self) -> None:
        data = {"roles": list(self._user_roles.values()), "limits": self._limits}
        try:
            config.atomic_write_text(self._path, json.dumps(data, indent=2, ensure_ascii=False))
        except Exception:  # noqa: BLE001
            log.warning("Failed to save %s", getattr(self._path, "name", self._path),
                        exc_info=True)

    @staticmethod
    def _merge_limits(patch: dict) -> dict:
        out = dict(DEFAULT_LIMITS)
        for k, (lo, hi) in _LIMIT_BOUNDS.items():
            v = patch.get(k)
            if isinstance(v, (int, float)):
                out[k] = max(lo, min(hi, int(v)))
        return out

    # --- odczyt ---
    def limits(self) -> dict:
        return dict(self._limits)

    def get(self, role_id: str) -> Optional[dict]:
        """Rola po id: nadpisanie usera ma pierwszeństwo nad wbudowaną."""
        if role_id in self._user_roles:
            return dict(self._user_roles[role_id])
        for r in BUILTIN_ROLES:
            if r["id"] == role_id:
                return dict(r)
        return None

    def list(self) -> list[dict]:
        """Wszystkie role (wbudowane nadpisane wpisami usera + role usera)."""
        merged: dict[str, dict] = {r["id"]: dict(r) for r in BUILTIN_ROLES}
        merged.update({rid: dict(r) for rid, r in self._user_roles.items()})
        return [merged[k] for k in sorted(merged)]

    # --- zapis (F4) ---
    def upsert_role(self, cfg: dict) -> dict:
        clean = _clean_role(cfg)
        if clean is None:
            raise ValueError("role requires a non-empty 'id'")
        clean["builtin"] = False
        self._user_roles[clean["id"]] = clean
        self._save()
        return clean

    def remove_role(self, role_id: str) -> bool:
        """Usuń nadpisanie/rolę usera. Wbudowane wracają do domyślnych. False, gdy brak."""
        if role_id in self._user_roles:
            del self._user_roles[role_id]
            self._save()
            return True
        return False

    def set_limits(self, patch: dict) -> dict:
        self._limits = self._merge_limits({**self._limits, **(patch or {})})
        self._save()
        return dict(self._limits)
