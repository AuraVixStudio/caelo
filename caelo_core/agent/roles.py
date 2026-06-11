"""Role subagentów + limity zespołu (M17-B2/B5/F4).

Rola = persona subagenta: opis, **zawężony zestaw narzędzi plikowych**, zakres
narzędzi MCP (`none`/`readonly`/`all`), flaga `worktree` (czy rola mutuje i musi
pracować w izolowanej kopii workspace), opcjonalny model (tiering kosztów — wciąż
„tylko Grok", różne warianty) i tryb bramki dla pod-sesji.

Wbudowane role (PLAN_M17 §0): researcher / reviewer = READONLY (bez worktree);
implementer = mutujące w worktree; tester = `run_command` w worktree. M19-B6 dodaje
role dla skilli-orkiestratorów: design-doc-reviewer / security-auditor = READONLY;
design-doc-writer / test-writer = mutujące w worktree. Użytkownik może je nadpisać/
dodać (`caelo_subagents.json`, atomowo + `load_json_or_backup`).

Bezpieczeństwo (B5): zakres roli NIGDY nie jest szerszy niż rodzica — egzekwowane
przez przecięcie z `parent_tools` w `effective_tools()`. `mcp:'all'` wciąż przechodzi
przez bramkę dla narzędzi mutujących (jak w agencie), więc to nie eskalacja.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Optional

import config  # type: ignore

from caelo_core import validation as V
from caelo_core.agent.permissions import MUTATING, READONLY

log = logging.getLogger(__name__)

# Kanoniczny zbiór narzędzi plikowych agenta (do walidacji zakresu ról).
ALL_FILE_TOOLS = sorted(READONLY | MUTATING)
MCP_SCOPES = ("none", "readonly", "all")

# M19-B11: warstwa persony + kontrakt I/O nad rolami (jak `bundled/personas/*.toml`
# z Grok CLI). `instructions` = wielolinijkowa persona (gdy brak — fallback na `prompt`);
# `inputs`/`outputs` = deklaracja czego subagent oczekuje / co ma zwrócić (prompt-steering).
MAX_INSTRUCTIONS = 8000      # cap persony (jak per-plik CAELO.md)
MAX_IO_FIELDS = 16           # limit pozycji inputs/outputs (anty-bloat configu)
IO_TYPES = ("text", "file")  # rodzaj pola I/O (jak persony CLI); inne → "text"


def _clean_io(items) -> list[dict]:
    """Oczyść listę pól I/O (inputs/outputs). Pozycja bez `name` → pominięta;
    `io_type` spoza IO_TYPES → 'text'; twardy limit liczby pól i długości opisu."""
    out: list[dict] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name") or "").strip()
        if not name:
            continue
        io_type = it.get("io_type") if it.get("io_type") in IO_TYPES else "text"
        out.append({
            "name": name,
            "io_type": io_type,
            "required": bool(it.get("required", False)),
            "description": str(it.get("description") or "")[:500],
        })
        if len(out) >= MAX_IO_FIELDS:
            break
    return out

# Wbudowane role — `tools` to dozwolone narzędzia PLIKOWE; `mcp` to zakres MCP.
# `worktree:true` ⇒ rola mutuje i pracuje w izolowanej kopii workspace (scalanie = B4).
BUILTIN_ROLES: list[dict] = [
    {
        "id": "researcher",
        "reasoning_effort": "high",
        "outputs": [
            {"name": "findings", "description": "Structured facts with file:line references."},
        ],
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
        "reasoning_effort": "high",
        "outputs": [
            {"name": "findings", "required": True,
             "description": "Prioritized issues, each with a file:line reference and rationale."},
            {"name": "verdict", "description": "Overall assessment (approve / needs work)."},
        ],
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
        "reasoning_effort": "high",
        "inputs": [
            {"name": "review_file", "io_type": "file", "required": False,
             "description": "Review notes to address (absent on first implementation)."},
        ],
        "outputs": [
            {"name": "summary", "required": True,
             "description": "What you changed and why (the diff awaits the user's merge review)."},
        ],
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
        "reasoning_effort": "low",
        "outputs": [
            {"name": "results", "required": True,
             "description": "What you ran, pass/fail, and any actionable failures."},
        ],
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
    # M19-B6: role dla skilli-orkiestratorów (pętle wieloagentowe). Persony wzorowane na
    # `bundled/personas/*.toml` z dystrybucji Grok CLI. READONLY tam, gdzie tylko krytyka/
    # audyt; worktree tam, gdzie rola PISZE (dokument/testy) — scalanie = B4 (review przy merge).
    {
        "id": "design-doc-writer",
        "reasoning_effort": "high",
        "inputs": [
            {"name": "review_file", "io_type": "file", "required": False,
             "description": "Reviewer notes to address (absent on the initial write)."},
        ],
        "outputs": [
            {"name": "design_doc", "io_type": "file", "required": True,
             "description": "The design document written to a sensible path (docs/ or design/)."},
            {"name": "summary", "description": "What the document covers and where you wrote it."},
        ],
        "label": "Design Doc Writer",
        "description": "Drafts and revises a design document in an isolated worktree.",
        "tools": ["read_file", "list_dir", "glob", "grep", "write_file", "edit_file"],
        "mcp": "readonly",
        "worktree": True,
        "model": "",
        "prompt": (
            "You are a DESIGN-DOC WRITER subagent working in an ISOLATED COPY of the "
            "workspace. Study the relevant code (read-only tools) and write a clear, "
            "concrete design document in Markdown for the assigned task: problem statement, "
            "proposed approach, key components/interfaces, data flow, edge cases, risks and "
            "a step-by-step plan. Write it to a sensible path (e.g. docs/ or design/). If "
            "you are revising after a review, address EVERY point raised. Reply with a short "
            "summary of the document and where you wrote it; it awaits the user's merge review."
        ),
        "builtin": True,
    },
    {
        "id": "design-doc-reviewer",
        "reasoning_effort": "high",
        "inputs": [
            {"name": "design_doc", "io_type": "file", "required": True,
             "description": "The design document to critique."},
        ],
        "outputs": [
            {"name": "concerns", "required": True,
             "description": "Prioritized, concrete, actionable concerns."},
            {"name": "verdict", "required": True,
             "description": "Explicit 'VERDICT: APPROVE' or 'VERDICT: REVISE' on its own line."},
        ],
        "label": "Design Doc Reviewer",
        "description": "Critiques a design document read-only for gaps, risks and simpler options.",
        "tools": ["read_file", "list_dir", "glob", "grep"],
        "mcp": "readonly",
        "worktree": False,
        "model": "",
        "prompt": (
            "You are a DESIGN-DOC REVIEWER subagent. Read the design document and the "
            "relevant code (read-only tools only) and critique the design: unaddressed "
            "requirements, hidden complexity, missing edge cases, security/performance "
            "risks, and simpler alternatives. Do NOT modify anything. Reply with a "
            "prioritized list of concerns (each concrete and actionable) and an explicit "
            "verdict on its own line: 'VERDICT: APPROVE' or 'VERDICT: REVISE'."
        ),
        "builtin": True,
    },
    {
        "id": "security-auditor",
        "reasoning_effort": "high",
        "outputs": [
            {"name": "findings", "required": True,
             "description": "Vulnerabilities with severity, file:line, the risk, and a fix "
                            "(state explicitly if none found)."},
        ],
        "label": "Security Auditor",
        "description": "Audits code read-only for security vulnerabilities.",
        "tools": ["read_file", "list_dir", "glob", "grep"],
        "mcp": "readonly",
        "worktree": False,
        "model": "",
        "prompt": (
            "You are a SECURITY AUDITOR subagent. Inspect the relevant code (read-only "
            "tools only) for vulnerabilities: injection (command/SQL), path traversal, "
            "authentication/authorization gaps, secret handling, unsafe deserialization, "
            "SSRF, and unvalidated input. Do NOT modify anything. Reply with a prioritized "
            "findings list — each with severity (high/medium/low), a file:line reference, "
            "the concrete risk, and a recommended fix. State explicitly if you find none."
        ),
        "builtin": True,
    },
    {
        "id": "test-writer",
        "reasoning_effort": "medium",
        "outputs": [
            {"name": "tests", "io_type": "file", "required": True,
             "description": "Test files you added/edited (the diff awaits merge review)."},
            {"name": "results", "required": True,
             "description": "What you tested and the run result (pass/fail)."},
        ],
        "label": "Test Writer",
        "description": "Writes and runs tests in an isolated worktree.",
        "tools": ["read_file", "list_dir", "glob", "grep", "write_file", "edit_file", "run_command"],
        "mcp": "all",
        "worktree": True,
        "model": "",
        "prompt": (
            "You are a TEST WRITER subagent working in an ISOLATED COPY of the workspace. "
            "Study the code under test and the project's existing test conventions, then "
            "write focused tests (write_file/edit_file) covering the key behaviors and edge "
            "cases. Run them with run_command (one program per call; no shell operators) and "
            "iterate until they pass or you have a clear, reported failure. Reply with a "
            "short summary: what you tested, the files you added, and the run result; the "
            "changes await the user's merge review."
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
        # M19-B9: poziom reasoning_effort roli (low/medium/high); "" = dziedzicz globalny.
        "reasoning_effort": V.normalize_effort(cfg.get("reasoning_effort")) or "",
        # M19-B11: persona (instructions) + kontrakt I/O (inputs/outputs).
        "instructions": str(cfg.get("instructions") or "")[:MAX_INSTRUCTIONS],
        "inputs": _clean_io(cfg.get("inputs")),
        "outputs": _clean_io(cfg.get("outputs")),
        "prompt": str(cfg.get("prompt") or ""),
        "builtin": bool(cfg.get("builtin", False)),
    }


def _normalize_role(role: dict) -> dict:
    """M19-B9/B11: uzupełnij brakujące pola wartościami domyślnymi i skanonizuj listy
    I/O. Stosowane do ról WBUDOWANYCH (trzymane jako surowe dict-y), by `get()`/`list()`
    zawsze zwracały pełny, spójny kształt (jak role użytkownika po `_clean_role`).
    Idempotentne."""
    r = dict(role)
    r.setdefault("reasoning_effort", "")
    r.setdefault("instructions", "")
    r["inputs"] = _clean_io(r.get("inputs"))
    r["outputs"] = _clean_io(r.get("outputs"))
    return r


def role_persona(role: dict) -> str:
    """M19-B11: persona roli do system promptu subagenta — `instructions`, a gdy brak,
    fallback na `prompt` (wstecznie z M17)."""
    return (role.get("instructions") or role.get("prompt") or "").strip()


def role_io_contract(role: dict) -> str:
    """M19-B11: deterministyczna rama kontraktu I/O (EN) do dopięcia w prompcie
    subagenta. Pusta, gdy rola nie deklaruje inputs/outputs."""
    inputs = role.get("inputs") or []
    outputs = role.get("outputs") or []
    if not inputs and not outputs:
        return ""

    def _fmt(f: dict) -> str:
        req = "required" if f.get("required") else "optional"
        desc = f.get("description") or ""
        return f"- {f.get('name', '?')} ({f.get('io_type', 'text')}, {req})" + (f": {desc}" if desc else "")

    lines: list[str] = []
    if inputs:
        lines.append("Inputs you may be given (in the task):")
        lines += [_fmt(f) for f in inputs]
    if outputs:
        if lines:
            lines.append("")
        lines.append("Outputs to produce (address each in your final summary):")
        lines += [_fmt(f) for f in outputs]
    return "\n".join(lines)


def role_system_prompt(role: dict) -> str:
    """M19-B11: złączona persona + kontrakt I/O dla `extra_system` subagenta. Pusty
    string, gdy rola nie ma ani persony, ani kontraktu (wołający → None)."""
    persona = role_persona(role)
    contract = role_io_contract(role)
    if persona and contract:
        return persona + "\n\n" + contract
    return persona or contract


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
        # 3.3-d: RLock — registry jest czytany z wątków subagentów (team.run: limits()/get())
        # i zapisywany z REST (/agent/team/roles,limits). Bez locka _save()'s iteracja po
        # _user_roles mogła trafić „dictionary changed size during iteration".
        self._lock = threading.RLock()
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
        with self._lock:
            return dict(self._limits)

    def get(self, role_id: str) -> Optional[dict]:
        """Rola po id: nadpisanie usera ma pierwszeństwo nad wbudowaną. Zwracana w
        pełnym, znormalizowanym kształcie (B9/B11 — `_normalize_role`)."""
        with self._lock:
            if role_id in self._user_roles:
                return _normalize_role(self._user_roles[role_id])
        for r in BUILTIN_ROLES:
            if r["id"] == role_id:
                return _normalize_role(r)
        return None

    def list(self) -> list[dict]:
        """Wszystkie role (wbudowane nadpisane wpisami usera + role usera), każda w
        znormalizowanym kształcie (B9/B11)."""
        merged: dict[str, dict] = {r["id"]: dict(r) for r in BUILTIN_ROLES}
        with self._lock:
            merged.update({rid: dict(r) for rid, r in self._user_roles.items()})
        return [_normalize_role(merged[k]) for k in sorted(merged)]

    # --- zapis (F4) ---
    def upsert_role(self, cfg: dict) -> dict:
        clean = _clean_role(cfg)
        if clean is None:
            raise ValueError("role requires a non-empty 'id'")
        clean["builtin"] = False
        with self._lock:
            self._user_roles[clean["id"]] = clean
            self._save()
        return clean

    def remove_role(self, role_id: str) -> bool:
        """Usuń nadpisanie/rolę usera. Wbudowane wracają do domyślnych. False, gdy brak."""
        with self._lock:
            if role_id in self._user_roles:
                del self._user_roles[role_id]
                self._save()
                return True
        return False

    def set_limits(self, patch: dict) -> dict:
        with self._lock:
            self._limits = self._merge_limits({**self._limits, **(patch or {})})
            self._save()
            return dict(self._limits)
