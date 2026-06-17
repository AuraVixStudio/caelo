"""Pętla agenta kodowania.

Sterowana zdarzeniami: każdy krok (tekst modelu, wywołanie narzędzia, prośba o
zgodę, wynik narzędzia) jest emitowany przez callback `emit`, a `request_approval`
blokuje do czasu decyzji użytkownika. `llm_fn` jest wstrzykiwany (test = mock).
"""

from __future__ import annotations

import json
from typing import Callable, List, Optional

import config  # type: ignore  # repo-root (sys.path z caelo_core/__init__.py)

from caelo_core.agent.caelomd import build_system_prompt
from caelo_core.agent.permissions import MUTATING, PermissionGate, command_metachars
from caelo_core.agent.tools import (
    TOOLS, execute_tool, normalize_plan, plan_summary, preview_change, web_search,
)
from caelo_core.agent.workspace import Workspace

# M17-B2: narzędzie orkiestratora do delegowania podzadań wyspecjalizowanym
# subagentom. Dostępne TYLKO orkiestratorowi (gdy wstrzyknięto `delegate_fn`);
# subagenci go nie dostają → głębia delegacji = 1 (B5, brak wnuków/fork-bomby).
DELEGATE_TOOL = {"type": "function", "function": {
    "name": "delegate",
    "description": (
        "Delegate one or more independent subtasks to specialized subagents that "
        "work in ISOLATED contexts and return concise summaries. Use for "
        "parallelizable work. Roles: 'researcher'/'reviewer' are read-only; "
        "'implementer'/'tester' make changes in an isolated copy you review and "
        "merge afterwards. Prefer delegating self-contained chunks; keep your own "
        "context clean and integrate the returned summaries."),
    "parameters": {"type": "object", "properties": {
        "tasks": {"type": "array", "description": "Subtasks to run (in parallel).",
                  "items": {"type": "object", "properties": {
                      "role": {"type": "string",
                               "description": "Subagent role id (e.g. researcher, "
                                              "reviewer, implementer, tester)."},
                      "task": {"type": "string",
                               "description": "Self-contained instruction for the subagent."},
                  }, "required": ["role", "task"]}},
    }, "required": ["tasks"]}}}

# M19-B3: narzędzie LSP (intel kodu, READONLY → bez bramki). Advertowane TYLKO gdy
# skonfigurowano serwer języka (ukryte gdy brak — by model nie planował wokół braku).
LSP_TOOL = {"type": "function", "function": {
    "name": "lsp",
    "description": (
        "Query the language server for code intelligence (read-only). Actions: "
        "'definition' (go to a symbol's definition), 'references' (find usages), "
        "'hover' (type/signature/docs at a position), 'documentSymbol' (symbols in a file). "
        "Give a workspace-relative path and 0-based line/character for cursor-based actions."),
    "parameters": {"type": "object", "properties": {
        "action": {"type": "string",
                   "enum": ["definition", "references", "hover", "documentSymbol"]},
        "path": {"type": "string", "description": "File path relative to the workspace root."},
        "line": {"type": "integer", "description": "0-based line (cursor-based actions)."},
        "character": {"type": "integer", "description": "0-based column (cursor-based actions)."},
    }, "required": ["action", "path"]}}}

# M19-B13: narzędzie web_fetch (egress sieciowy POD BRAMKĄ — MUTATING). Advertowane TYLKO
# gdy włączone (`config.WEB_FETCH_ENABLED`) i tylko orkiestratorowi (subagenci go nie mają —
# zakres roli ich nie obejmuje). https-only/allowlista/cap/SSRF egzekwuje `tools.web_fetch`.
WEB_FETCH_TOOL = {"type": "function", "function": {
    "name": "web_fetch",
    "description": (
        "Fetch the text content of an https:// URL (network read; REQUIRES approval). "
        "Returns the page text (HTML is reduced to text). Only https is allowed, the size "
        "is capped, and loopback/private hosts are refused. Use for docs/reference lookups."),
    "parameters": {"type": "object", "properties": {
        "url": {"type": "string", "description": "The https:// URL to fetch."},
        "max_bytes": {"type": "integer", "description": "Optional cap on bytes to read."},
    }, "required": ["url"]}}}

# Faza-G/TOP1: narzędzie web_search (live web/X search; READONLY → BEZ bramki, jak lsp).
# Advertowane TYLKO gdy włączone (`config.WEB_SEARCH_ENABLED`, domyślnie ON) i tylko
# orkiestratorowi (subagenci mają zawężony zbiór plikowy). Reużywa `responses_client`
# live-search; zwraca syntezę + cytowania. ŚWIADOMIE poza zbiorem `permissions.READONLY` —
# tam rozszerzyłoby ALL_FILE_TOOLS/PARENT_FILE_TOOLS (role/subagenci); jak `delegate`, ma
# własną wczesną ścieżkę w `_handle_tool_call`.
WEB_SEARCH_TOOL = {"type": "function", "function": {
    "name": "web_search",
    "description": (
        "Search the live web and X (Twitter) for current information and get back a "
        "synthesized answer with cited sources (read-only; no approval needed). Use it for "
        "anything newer than your training data — recent events, current library/API "
        "versions, release notes, unfamiliar error messages. Pass one focused "
        "natural-language query per call."),
    "parameters": {"type": "object", "properties": {
        "query": {"type": "string", "description": "The search query (natural language)."},
        "sources": {"type": "array", "items": {"type": "string", "enum": ["web", "x", "news"]},
                    "description": "Optional source filter (default: web + x)."},
    }, "required": ["query"]}}}

# Faza-G/TOP3: narzędzie update_plan — live checklist (TODO) bieżącego zadania (jak TodoWrite).
# META: nic nie mutuje → BEZ bramki, własna wczesna ścieżka jak `delegate` (świadomie poza
# MUTATING/READONLY). Emituje ramkę `plan` renderowaną w AgentPanel. Advertowane orkiestratorowi
# (subagenci raportują postęp przez TeamView, nie przez własny plan).
UPDATE_PLAN_TOOL = {"type": "function", "function": {
    "name": "update_plan",
    "description": (
        "Maintain a short, step-by-step plan for the current task as a live checklist the "
        "user sees. Call it when you START a non-trivial task (lay out the steps) and AGAIN "
        "whenever a step's status changes — always pass the FULL ordered list. Keep steps "
        "concise; mark exactly one step 'in_progress' while you work on it, 'completed' when done."),
    "parameters": {"type": "object", "properties": {
        "steps": {"type": "array", "description": "The full ordered plan.",
                  "items": {"type": "object", "properties": {
                      "step": {"type": "string", "description": "Short description of the step."},
                      "status": {"type": "string",
                                 "enum": ["pending", "in_progress", "completed"]},
                  }, "required": ["step"]}},
    }, "required": ["steps"]}}}

SYSTEM_PROMPT = (
    "You are Caelo Code, an agentic coding assistant working in the user's local workspace.\n"
    "You can read, search, write and edit files, and run shell commands via tools.\n"
    "Guidelines:\n"
    "- Explore with read_file/list_dir/glob/grep before changing anything.\n"
    "- Prefer edit_file with a unique old_string; use write_file for new files.\n"
    "- edit_file old_string must be copied VERBATIM from read_file output — exact "
    "indentation (tabs vs spaces) and whitespace. If an edit returns 'old_string not "
    "found', do NOT retry the same string: re-read the file, or rewrite the whole file "
    "with write_file. Never loop on a failing edit.\n"
    "- Keep changes minimal and focused on the request.\n"
    "- All paths are relative to the workspace root.\n"
    "- run_command runs ONE program per call. Shell operators (&&, ||, |, ;, &, >, <, "
    "2>&1, backticks, $()) are NOT allowed and the call will be rejected — issue separate "
    "run_command calls instead, and never redirect output (stdout AND stderr are already "
    "returned to you). To make a directory use 'mkdir <path>' alone; to chain build steps, "
    "call run_command once per step.\n"
    "- After finishing, give a short summary of what you changed."
)

# M13-B2: dodatek do system promptu w trybie planowania — żadnych mutacji, tylko plan.
PLAN_MODE_PROMPT = (
    "\n\nPLAN MODE IS ACTIVE. Do NOT modify anything yet. Use ONLY the read-only "
    "tools (read_file/list_dir/glob/grep) to investigate, then reply with a clear, "
    "numbered, step-by-step plan of the changes you would make. write_file, "
    "edit_file and run_command are DISABLED until the user approves the plan."
)

# M13: tryby agenta (jak „Mode" w Claude Code) — sterują bramką zatwierdzania:
#   ask          — pytaj o każdą mutację spoza allowlisty (domyślny, dotychczasowy)
#   accept-edits — auto-akceptuj write/edit (cofalne przez checkpointy); komendy nadal pytaj
#   plan         — tylko READONLY; agent proponuje plan, mutacje zablokowane
#   bypass       — auto-akceptuj wszystko (write/edit/run) bez pytania (ryzykowne)
AGENT_MODES = ("ask", "accept-edits", "plan", "bypass")
DEFAULT_MODE = "ask"

# Bezpiecznik pętli (LIVE 2026-06-17): ile razy IDENTYCZNE wywołanie (name+args) może
# wystąpić w jednej turze, zanim uznamy to za pętlę i przerwiemy. Próg z zapasem na
# legalne ponowienia (np. read_file po nieudanej edycji), ale daleko od korupcji pliku.
LOOP_GUARD_LIMIT = 3

# M19-B10: auto-compact — zwijanie najstarszych ZAMKNIĘTYCH tur, gdy historia rośnie.
COMPACT_SUMMARY_HEADER = "[Earlier conversation summarized to save context]"


def _content_text(content) -> str:
    """Tekst wiadomości: string wprost albo sklejone części tekstowe (multimodal)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            p.get("text", "") for p in content
            if isinstance(p, dict) and p.get("type") == "text" and p.get("text")
        )
    return ""


def _msg_chars(m: dict) -> int:
    n = len(_content_text(m.get("content")))
    for tc in m.get("tool_calls") or []:
        fn = tc.get("function", {}) or {}
        n += len(str(fn.get("name", ""))) + len(str(fn.get("arguments", "")))
    return n


def _history_chars(history: list) -> int:
    return sum(_msg_chars(m) for m in history if isinstance(m, dict))


def _compact_boundary(history: list, target_chars: int) -> int:
    """Najwcześniejszy indeks wiadomości `user` taki, że zachowany SUFIKS (od niego do
    końca) mieści się w `target_chars`, zawsze zostawiając ≥ ostatnią turę. Zwraca 0,
    gdy nie ma czego bezpiecznie zwinąć (potrzeba ≥2 tur). Cięcie NA GRANICY `user`
    gwarantuje balans (każdy assistant.tool_calls ma swoje `tool` w obrębie tury)."""
    user_idxs = [i for i, m in enumerate(history)
                 if isinstance(m, dict) and m.get("role") == "user"]
    if len(user_idxs) < 2:
        return 0
    boundary = user_idxs[-1]  # minimum: zachowaj ostatnią turę
    for idx in reversed(user_idxs[:-1]):
        if _history_chars(history[idx:]) <= target_chars:
            boundary = idx
        else:
            break
    return boundary


def _digest_prefix(prefix: list, max_chars: int) -> str:
    """Deterministyczny digest zwijanych wiadomości (BEZ sieci): role + skrócona treść,
    z twardym capem całości. Zachowuje wątek (co proszono / co zrobiono)."""
    parts: list[str] = []
    for m in prefix:
        if not isinstance(m, dict):
            continue
        role = m.get("role", "?")
        text = _content_text(m.get("content")).strip()
        if not text:
            tcs = m.get("tool_calls") or []
            if tcs:
                names = ", ".join((t.get("function", {}) or {}).get("name", "?") for t in tcs)
                text = f"(called tools: {names})"
            else:
                continue
        parts.append(f"- {role}: {text[:300]}")
    digest = "\n".join(parts)
    if len(digest) > max_chars:
        digest = digest[:max_chars].rstrip() + "\n… (older details omitted)"
    return digest


def compact_history(history: list, *, threshold_chars: int) -> list:
    """M19-B10: zwiń najstarsze zamknięte tury w jeden blok-streszczenie, gdy historia
    przekracza próg. CZYSTA funkcja (testowalna). Zwraca NOWĄ listę; **balans zachowany**
    (cięcie na granicy `user`). Bez zmian, gdy nic bezpiecznego do zwinięcia / pod progiem."""
    if threshold_chars <= 0 or _history_chars(history) <= threshold_chars:
        return history
    target = max(1, threshold_chars // 2)
    boundary = _compact_boundary(history, target)
    if boundary <= 0:
        return history
    prefix, suffix = history[:boundary], history[boundary:]
    digest = _digest_prefix(prefix, target)
    summary = {"role": "user", "content": COMPACT_SUMMARY_HEADER + "\n" + digest}
    return [summary] + suffix

# Sygnatura llm_fn:
#   (api_key, base_url, messages, model, temperature, tools, on_text, stop_flag) -> assistant_msg
LlmFn = Callable[..., dict]
Emit = Callable[[dict], None]
RequestApproval = Callable[[str, str, Optional[dict]], str]  # (id, name, detail) -> decision


class AgentSession:
    def __init__(
        self,
        workspace: Workspace,
        gate: PermissionGate,
        llm_fn: LlmFn,
        api_key_provider: Callable[[], str],
        base_url: str,
        emit: Emit,
        request_approval: RequestApproval,
        max_iters: int = 50,
        checkpoints_provider: Optional[Callable[[], object]] = None,
        caelo_md_global_dir: Optional[str] = None,
        mcp: Optional[object] = None,
        hooks: Optional[object] = None,
        skills: Optional[object] = None,
        tool_names: Optional[set] = None,
        delegate_fn: Optional[Callable[[list], str]] = None,
        extra_system: Optional[str] = None,
        on_turn: Optional[Callable[[], None]] = None,
        lsp_provider: Optional[Callable[[], object]] = None,
        memory: Optional[object] = None,
        reasoning_effort: Optional[str] = None,
    ) -> None:
        self.ws = workspace
        self.gate = gate
        self.llm_fn = llm_fn
        self.api_key_provider = api_key_provider
        self.base_url = base_url
        self.emit = emit
        self.request_approval = request_approval
        self.max_iters = max_iters
        # M17-B1: zawężenie narzędzi PLIKOWYCH (rola subagenta). None → wszystkie.
        # Egzekwowane DWUKROTNIE: nieadvertowane modelowi I odrzucane w pętli (gdyby
        # model je halucynował) — brak eskalacji zakresu.
        self._tool_names = set(tool_names) if tool_names is not None else None
        # M17-B2: orkiestrator deleguje przez to narzędzie; subagenci mają None.
        self._delegate_fn = delegate_fn
        # M17-B1: dodatkowy system prompt (persona roli subagenta).
        self._extra_system = extra_system
        # M17-B5: callback liczący tury (budżet zespołu). Wołany raz na iterację.
        self._on_turn = on_turn
        # M17-B6: telemetria pod-sesji (tury LLM, wywołania narzędzi, tokeny z usage).
        self.turns = 0
        self.tool_calls = 0
        self.usage = {"input_tokens": 0, "output_tokens": 0}
        # Miernik okna kontekstowego: tokeny ostatniego promptu wysłanego do modelu.
        # `last_input_tokens` = realne (usage.input z ostatniego wywołania, gdy serwer je
        # zwróci); `last_context_tokens` = szacunek (~4 znaki/token) jako fallback offline.
        self.last_input_tokens = 0
        self.last_context_tokens = 0
        # M14-B2: menedżer MCP (duck-typed — bez twardego importu, jak checkpoints).
        # None → brak narzędzi MCP. tool_defs_for_responses/is_mcp_tool/is_mutating/
        # describe_tool/call_tool to kontrakt (patrz caelo_core/mcp/manager.py).
        self.mcp = mcp
        # M14-B5: menedżer hooków (pre/post-tool, pre-session). None → brak hooków.
        self.hooks = hooks
        # M14-B6: biblioteka skilli (duck-typed: injected_text()). None → brak skilli.
        self.skills = skills
        # M13-B3: dostawca menedżera checkpointów (współdzielony z REST przez Backend);
        # None → checkpointy wyłączone (np. w self-checkach starej ścieżki).
        self.checkpoints_provider = checkpoints_provider
        # M13-B4: katalog globalnego CAELO.md (domyślnie config.DATA_DIR).
        self.caelo_md_global_dir = caelo_md_global_dir
        # M19-B3: dostawca menedżera LSP (duck-typed: enabled()/query()/diagnostics()).
        # None → narzędzie lsp i pasywna diagnostyka wyłączone (ukryte przed modelem).
        self.lsp_provider = lsp_provider
        # M19-B8: pamięć hybrydowa (duck-typed: injected_text(query, project_id=) -> str).
        # None → wyłączona. Wstrzykiwana RAZ, na 1. turze (z pierwszego promptu usera).
        self.memory = memory
        self._memory_block = ""
        self._memory_done = False
        # M19-B9: domyślny poziom reasoning_effort (np. globalny z ustawień / rola
        # subagenta); per-tura `run_turn(reasoning_effort=…)` może go nadpisać.
        self._default_effort = reasoning_effort
        self._reasoning_effort = reasoning_effort
        self.history: List[dict] = []
        self._mode = DEFAULT_MODE  # M13: tryb bieżącej tury (ask/accept-edits/plan/bypass)
        self._cur_model = ""  # Faza-G/TOP1: model bieżącej tury (web_search → live-search)

    def _checkpoints(self):
        if not self.checkpoints_provider:
            return None
        try:
            return self.checkpoints_provider()
        except Exception:  # noqa: BLE001
            return None

    def _lsp(self):
        """M19-B3: menedżer LSP dla bieżącego workspace (lub None). Włączony, gdy
        zwraca obiekt z `enabled()==True` (są skonfigurowane serwery)."""
        if not self.lsp_provider:
            return None
        try:
            mgr = self.lsp_provider()
            return mgr if (mgr is not None and mgr.enabled()) else None
        except Exception:  # noqa: BLE001
            return None

    def _build_system_prompt(self) -> str:
        """M13-B4: bazowy prompt + reguły CAELO.md (workspace nadpisuje global) +
        (M13-B2) instrukcja trybu planowania. Liczone per tura (workspace może się
        zmienić, plik CAELO.md mógł zostać zedytowany)."""
        global_dir = self.caelo_md_global_dir or getattr(config, "DATA_DIR", None)
        ws_root = self.ws.root if self.ws else None
        prompt = build_system_prompt(SYSTEM_PROMPT, ws_root, global_dir)
        # M14-B6: wstrzyknij instrukcje WŁĄCZONYCH skilli (jak CAELO.md). Błąd/duże tolerowane.
        if self.skills is not None:
            try:
                extra = self.skills.injected_text()
                if extra:
                    prompt += "\n\n" + extra
            except Exception:  # noqa: BLE001
                pass
        # M19-B8: pamięć hybrydowa — top-K wspomnień policzone na 1. turze (po CAELO.md
        # i skillach, jak rekomenduje plan). Pusty blok, gdy wyłączone/brak trafień.
        if self._memory_block:
            prompt += "\n\n" + self._memory_block
        # M17-B1: persona roli subagenta (zawężony prompt). Idzie po CAELO.md/skillach.
        if self._extra_system:
            prompt += "\n\n" + self._extra_system
        if self._mode == "plan":
            prompt += PLAN_MODE_PROMPT
        return prompt

    def _maybe_compact(self) -> None:
        """M19-B10: opt-in zwijanie historii przy przekroczeniu progu (przed budową
        `messages`). Błąd połknięty — kompakcja nigdy nie wywraca tury."""
        if not getattr(config, "AGENT_AUTOCOMPACT", False):
            return
        try:
            self.history = compact_history(
                self.history,
                threshold_chars=getattr(config, "AGENT_COMPACT_THRESHOLD_CHARS", 0),
            )
        except Exception:  # noqa: BLE001
            pass

    def _maybe_inject_memory(self, query: str) -> None:
        """M19-B8: na PIERWSZEJ turze policz blok pamięci z promptu usera (raz na sesję).
        Błąd połknięty — pamięć nigdy nie wywraca tury."""
        if self.memory is None or self._memory_done:
            return
        self._memory_done = True
        try:
            self._memory_block = self.memory.injected_text(query) or ""
        except Exception:  # noqa: BLE001
            self._memory_block = ""

    def _auto_approves(self, name: str) -> bool:
        """M13: czy bieżący tryb pomija dialog zatwierdzenia dla narzędzia `name`.
        bypass → wszystko; accept-edits → tylko write/edit (komendy i MCP nadal pytane)."""
        if self._mode == "bypass":
            return True
        if self._mode == "accept-edits" and name in ("write_file", "edit_file"):
            return True
        return False

    def _all_tools(self) -> list:
        """Narzędzia plikowe + (M14-B2) odkryte narzędzia MCP + (M17-B2) delegate.

        M17-B1: gdy `_tool_names` ustawione (rola subagenta), advertuj tylko ten
        podzbiór narzędzi plikowych. M17-B2: dołącz `delegate` tylko dla orkiestratora
        (gdy `_delegate_fn` wstrzyknięte) — subagenci go nie widzą (głębia = 1)."""
        if self._tool_names is None:
            tools = list(TOOLS)
        else:
            tools = [t for t in TOOLS
                     if t.get("function", {}).get("name") in self._tool_names]
        if self.mcp is not None:
            try:
                tools += self.mcp.tool_defs_for_responses()
            except Exception:  # noqa: BLE001
                pass
        if self._delegate_fn is not None:
            tools.append(DELEGATE_TOOL)
        # M19-B3: advertuj `lsp` tylko gdy skonfigurowano serwer języka (ukryte inaczej).
        if self._lsp() is not None:
            tools.append(LSP_TOOL)
        # M19-B13: web_fetch tylko gdy włączone i tylko dla orkiestratora (subagenci mają
        # zawężony zbiór plikowy — `_tool_allowed` i tak by je odrzucił, więc nie advertuj).
        if getattr(config, "WEB_FETCH_ENABLED", False) and self._tool_names is None:
            tools.append(WEB_FETCH_TOOL)
        # Faza-G/TOP1: web_search tylko gdy włączone i tylko orkiestratorowi (subagenci mają
        # zawężony zbiór plikowy). READONLY — biegnie bez bramki, jak lsp.
        if getattr(config, "WEB_SEARCH_ENABLED", False) and self._tool_names is None:
            tools.append(WEB_SEARCH_TOOL)
        # Faza-G/TOP3: update_plan (live checklist) — orkiestratorowi (subagenci raportują
        # postęp przez TeamView). META/READONLY → bez kosztu/sieci, więc bez flagi (zawsze on).
        if self._tool_names is None:
            tools.append(UPDATE_PLAN_TOOL)
        return tools

    def _tool_allowed(self, name: str) -> bool:
        """M17-B1: czy narzędzie plikowe wolno wywołać w tej (pod)sesji. Narzędzia
        MCP i `delegate` mają osobne ścieżki; filtr dotyczy tylko zbioru plikowego."""
        if self._tool_names is None:
            return True
        if name in self._tool_names:
            return True
        # MCP/delegate nie są w zbiorze plikowym — ich dozwolenie liczone osobno.
        return self._is_mcp(name) or (name == "delegate" and self._delegate_fn is not None)

    def _is_mcp(self, name: str) -> bool:
        return self.mcp is not None and self.mcp.is_mcp_tool(name)

    def _is_mutating(self, name: str) -> bool:
        """Czy narzędzie wymaga zgody/bramki (mutuje stan). Plikowe: zbiór MUTATING.
        MCP: `readOnlyHint` z adnotacji (brak → mutujące, bezpieczny default)."""
        if self._is_mcp(name):
            return bool(self.mcp.is_mutating(name))
        return name in MUTATING

    def run_turn(self, user_text: str, model: str, temperature: float = 0.2,
                 stop_flag: Optional[Callable[[], bool]] = None,
                 images: Optional[List[str]] = None, mode: str = DEFAULT_MODE,
                 reasoning_effort: Optional[str] = None) -> None:
        stop = stop_flag or (lambda: False)
        self._mode = mode if mode in AGENT_MODES else DEFAULT_MODE
        # Faza-G/TOP1: model bieżącej tury — web_search reużywa go do live-search.
        self._cur_model = model
        # M19-B9: None = zachowaj domyślny effort sesji; podany = nadpisz na tę turę.
        self._reasoning_effort = reasoning_effort if reasoning_effort is not None else self._default_effort
        # M13-B3: otwórz grupę checkpointów dla tej tury (leniwa — powstanie dopiero
        # przy 1. mutacji). W trybie planowania NIE zaczynamy tury (nic nie zmienia).
        cp = self._checkpoints()
        if cp is not None and self._mode != "plan":
            try:
                cp.on_event = self.emit  # zdarzenia „checkpoint" lecą po WS
                cp.begin_turn(label=user_text)
            except Exception:  # noqa: BLE001
                pass
        if images:
            # Treść multimodalna: tekst + załączone obrazy (data-URI / URL).
            content: object = [{"type": "text", "text": user_text}] + [
                {"type": "image_url", "image_url": {"url": u}} for u in images
            ]
        else:
            content = user_text
        self.history.append({"role": "user", "content": content})

        # M19-B10: zwiń najstarsze tury, gdy historia przekroczy próg (opt-in; przed
        # budową `messages`). Bieżąca tura (ostatni `user`) jest zawsze zachowana.
        self._maybe_compact()

        # M19-B8: na 1. turze policz blok pamięci z promptu usera (przed system promptem).
        self._maybe_inject_memory(user_text)
        system_prompt = self._build_system_prompt()  # M13-B4: CAELO.md + (B2) plan mode
        # M14-B5: hook pre_session (deterministyczny; np. skrypt setup / wpis audytu).
        if self.hooks is not None:
            try:
                self.hooks.run_pre_session(user_text, workspace=self.ws, emit=self.emit)
            except Exception:  # noqa: BLE001
                pass
        # M14-B2: narzędzia plikowe agenta + odkryte narzędzia MCP (namespaced). Liczone
        # raz na turę (serwer MCP może wystartować/zatrzymać się między turami).
        all_tools = self._all_tools()
        # Bezpiecznik pętli (LIVE 2026-06-17): model bywa, że w kółko powtarza TEN SAM
        # tool_call (np. edit_file z identycznym old/new_string) ignorując instrukcję
        # „Never loop on a failing edit" — co korumpuje plik (N× ta sama linia) i pali
        # iteracje. Liczymy sygnatury wywołań w obrębie TURY; po przekroczeniu progu
        # kończymy turę czysto (zbalansowana historia + komunikat), zamiast pętlić.
        self._repeat_counts: dict[str, int] = {}
        for _ in range(self.max_iters):
            if stop():
                self.emit({"type": "stopped"})
                return
            # M17-B5: zlicz turę PRZED wywołaniem LLM (budżet zespołu). on_turn może
            # podbić wspólny licznik; kolejny `stop()` (z budżetem) przerwie pętlę.
            self.turns += 1
            if self._on_turn is not None:
                try:
                    self._on_turn()
                except Exception:  # noqa: BLE001
                    pass
            if stop():  # budżet mógł właśnie zostać przekroczony
                self.emit({"type": "stopped"})
                return
            # self.history jest jedynym źródłem prawdy (P0-5) — budujemy z niego
            # `messages` co iterację, by zawsze zawierało odpowiedzi `tool`.
            messages = [{"role": "system", "content": system_prompt}] + self.history
            # Miernik okna kontekstowego: szacuj rozmiar promptu tej iteracji (fallback,
            # gdy serwer nie zwraca usage). Ostatnia iteracja = bieżące zajęcie kontekstu.
            self.last_context_tokens = self._estimate_tokens(messages)
            # M19-B9: `reasoning_effort` dokładane TYLKO gdy ustawione — mock LLM bez
            # tego parametru (selfchecki) nie dostaje nieoczekiwanego kwargu (zero regresji).
            llm_kwargs: dict = {
                "on_text": lambda full: self.emit({"type": "text", "full": full}),
                "stop_flag": stop,
            }
            if self._reasoning_effort:
                llm_kwargs["reasoning_effort"] = self._reasoning_effort
            assistant = self.llm_fn(
                self.api_key_provider(), self.base_url, messages, model, temperature, all_tools,
                **llm_kwargs,
            )
            # M17-B6: zbierz usage (tokeny) i NIE wysyłaj go z powrotem do xAI —
            # zdejmij z wiadomości przed dopisaniem do historii (czysty kontrakt).
            self._accumulate_usage(assistant.pop("usage", None) if isinstance(assistant, dict) else None)
            self.history.append(assistant)
            # Live miernik kontekstu/tokenów — po KAŻDYM wywołaniu LLM (nie tylko na końcu
            # tury), żeby panel aktualizował się w trakcie pracy (długa tura ≠ pusty licznik).
            self._emit_usage()

            tool_calls = assistant.get("tool_calls") or []
            if not tool_calls:
                self.emit({"type": "assistant_done", "content": assistant.get("content") or ""})
                return

            for idx, tc in enumerate(tool_calls):
                if stop():
                    # P0-5: Stop w środku batcha — dopisz syntetyczne wyniki dla
                    # nieobsłużonych tool_calls, by historia była zbalansowana.
                    self._finalize_interrupted(tool_calls[idx:])
                    self.emit({"type": "stopped"})
                    return
                # Bezpiecznik pętli: ten sam (name+args) powtórzony > LOOP_GUARD_LIMIT razy
                # w tej turze = pętla. Dopisz zbalansowane wyniki dla tego i pozostałych
                # wywołań, zgłoś użytkownikowi i zakończ turę (kontekst zostaje spójny —
                # „send another message" wznawia). NIE wykonuj wywołania (chroni plik).
                sig = self._call_signature(tc)
                self._repeat_counts[sig] = self._repeat_counts.get(sig, 0) + 1
                if self._repeat_counts[sig] > LOOP_GUARD_LIMIT:
                    self._finalize_interrupted(
                        tool_calls[idx:], reason="loop guard: identical tool call repeated")
                    fn = tc.get("function", {}) or {}
                    self.emit({"type": "info", "message": (
                        f"Stopped: the agent repeated the same action "
                        f"('{fn.get('name', '?')}') {self._repeat_counts[sig]} times "
                        "(loop guard). Send another message to continue or rephrase the task.")})
                    self.emit({"type": "stopped"})
                    return
                try:
                    self._handle_tool_call(tc, stop)
                except Exception as exc:  # noqa: BLE001
                    # Błąd obsługi narzędzia nie może zostawić wiadomości assistant
                    # z nieodpowiedzianymi tool_calls (następny request → 400).
                    self._finalize_interrupted(tool_calls[idx:], reason="error during tool execution")
                    self.emit({"type": "error", "error": str(exc)})
                    return

        # Limit iteracji wyczerpany. Zamiast surowego błędu (utracona tura) wymuś
        # JEDNĄ finalną odpowiedź BEZ narzędzi — model streszcza, co znalazł, i oddaje
        # plan/odpowiedź z dotychczasowego kontekstu. Znacznie lepszy UX niż dawne
        # „Max iterations reached", bo użytkownik dostaje użyteczny wynik + jasną
        # informację, że może kontynuować kolejną wiadomością.
        self._finalize_on_limit(system_prompt, model, temperature, stop)

    def _finalize_on_limit(self, system_prompt: str, model: str, temperature: float,
                           stop: Callable[[], bool]) -> None:
        """Po wyczerpaniu `max_iters`: jedno wywołanie LLM BEZ narzędzi, by oddać
        użyteczne podsumowanie/plan zamiast samego błędu. `tools=[]` → model nie może
        wołać narzędzi, więc na pewno zwróci treść. Tolerancyjne na błędy (fallback do
        krótkiej notki). Ostatni wpis historii to zbalansowany wynik `tool`, więc
        dopisanie wiadomości `assistant` (bez `tool_calls`) jest poprawne (kontrakt xAI)."""
        NOTE = "_Reached the step limit for this turn — send another message to continue._"
        content = ""
        try:
            llm_kwargs: dict = {
                "on_text": lambda full: self.emit({"type": "text", "full": full}),
                "stop_flag": stop,
            }
            if self._reasoning_effort:
                llm_kwargs["reasoning_effort"] = self._reasoning_effort
            messages = (
                [{"role": "system", "content": system_prompt}]
                + self.history
                + [{"role": "user", "content": (
                    "You have reached the step limit for this turn. Do NOT call any "
                    "tools. Summarize what you found and give your best answer or plan "
                    "from the context so far. If the task is unfinished, state clearly "
                    "what remains so the next message can continue.")}]
            )
            assistant = self.llm_fn(self.api_key_provider(), self.base_url, messages,
                                    model, temperature, [], **llm_kwargs)
            self._accumulate_usage(
                assistant.pop("usage", None) if isinstance(assistant, dict) else None)
            self._emit_usage()
            content = (assistant.get("content") or "").strip() if isinstance(assistant, dict) else ""
        except Exception:  # noqa: BLE001
            content = ""
        plain = content or (
            "I reached the step limit for this turn before finishing. Send another "
            "message and I'll continue from where I left off.")
        # Historia: czysta treść (bez markdownowej notki UI) — by wznowienie/„kontynuuj"
        # miały spójny kontekst. Wyświetlenie: treść + notka o limicie.
        self.history.append({"role": "assistant", "content": plain})
        display = plain if not content else (content + "\n\n" + NOTE)
        self.emit({"type": "text", "full": display})
        self.emit({"type": "assistant_done", "content": display})

    def _finalize_interrupted(self, pending: List[dict], reason: str = "interrupted") -> None:
        """P0-5: dopisz syntetyczny wynik `tool` dla każdego nieobsłużonego
        `tool_call`. Wiadomość `assistant` z N `tool_calls` MUSI mieć N odpowiedzi
        `tool` (kontrakt xAI/OpenAI) — inaczej następny request zwraca 400."""
        for tc in pending:
            fn = tc.get("function", {}) or {}
            call_id = tc.get("id") or fn.get("name", "")
            self.emit({"type": "tool_result", "id": call_id, "ok": False, "summary": reason})
            self.history.append({"role": "tool", "tool_call_id": call_id, "content": reason})

    @staticmethod
    def _call_signature(tc: dict) -> str:
        """Stabilna sygnatura wywołania narzędzia (name + znormalizowane args) dla
        bezpiecznika pętli. Args parsowane i re-serializowane z `sort_keys`, by drobne
        różnice formatowania nie myliły licznika; fallback do surowego stringa."""
        fn = tc.get("function", {}) or {}
        name = fn.get("name", "")
        raw = fn.get("arguments") or ""
        try:
            norm = json.dumps(json.loads(raw), sort_keys=True, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            norm = raw
        return name + "\x00" + norm

    def _handle_tool_call(self, tc: dict, stop: Optional[Callable[[], bool]] = None) -> None:
        fn = tc.get("function", {}) or {}
        name = fn.get("name", "")
        call_id = tc.get("id") or name
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except Exception:
            args = {}

        self.emit({"type": "tool_call", "id": call_id, "name": name, "args": args})
        self.tool_calls += 1  # M17-B6: telemetria

        # M17-B2: delegacja do subagentów (tylko orkiestrator ma delegate_fn).
        # Obsługiwana PRZED bramką/hookami — to prymityw orkiestracji, nie mutacja
        # plików; subagenci mają własne bramki/hooki w swoich pod-sesjach.
        if name == "delegate" and self._delegate_fn is not None:
            self._handle_delegate(call_id, args)
            return

        # M19-B3: narzędzie LSP — READONLY (bez bramki/hooków mutacji), własna ścieżka.
        if name == "lsp":
            self._handle_lsp(call_id, args)
            return

        # M17-B1: odrzuć narzędzie spoza zakresu roli (gdyby model je wyhalucynował) —
        # twarda granica zakresu, nie tylko brak w advertised tools (brak eskalacji).
        if not self._tool_allowed(name):
            note = (f"Tool '{name}' is not available to this subagent role. "
                    "Use only the tools you were given.")
            self.emit({"type": "tool_result", "id": call_id, "ok": False,
                       "summary": "Tool not allowed for this role"})
            self.history.append({"role": "tool", "tool_call_id": call_id, "content": note})
            return

        # Faza-G/TOP1: web_search — READONLY (bez bramki/hooków mutacji), własna ścieżka jak
        # lsp. PO `_tool_allowed` (to PŁATNE wywołanie sieciowe — subagent spoza zakresu dostał
        # już odmowę wyżej) i PRZED bramką/plan-mode (research dozwolony też w plan mode).
        if name == "web_search":
            self._handle_web_search(call_id, args, stop)
            return

        # Faza-G/TOP3: update_plan — live checklist (META, bez bramki/hooków mutacji). Po
        # `_tool_allowed` (orkiestrator-only) i przed bramką/plan-mode (to nie mutacja —
        # dozwolone też w plan mode, gdzie agent rozpisuje kroki).
        if name == "update_plan":
            self._handle_update_plan(call_id, args)
            return

        is_mcp = self._is_mcp(name)
        mutating = self._is_mutating(name)

        # M13-B2: w trybie planowania mutacje są wyłączone (też mutujące narzędzia MCP) —
        # odpowiedz modelowi czytelnym komunikatem (kontynuuje planowanie), nie wykonuj.
        if self._mode == "plan" and mutating:
            note = (f"Blocked in plan mode: '{name}' is disabled until the plan is "
                    "approved. Keep using read-only tools and finish the plan.")
            self.emit({"type": "tool_result", "id": call_id, "ok": False,
                       "summary": "Blocked in plan mode"})
            self.history.append({"role": "tool", "tool_call_id": call_id, "content": note})
            return

        # M14-B5: hook pre_tool (deterministyczny, niezależny od modelu) — może
        # ZABLOKOWAĆ wywołanie zanim dojdzie do bramki/wykonania (np. `rm -rf`).
        blocked = self._run_pre_tool_hooks(call_id, name, args)
        if blocked is not None:
            self.emit({"type": "tool_result", "id": call_id, "ok": False, "summary": blocked})
            self.history.append({"role": "tool", "tool_call_id": call_id,
                                 "content": f"Blocked by hook: {blocked}"})
            return

        # M19-B4: reguła deny (glob) — TWARDA odmowa, też dla narzędzi READONLY
        # (Read/Grep) i niezależnie od trybu (też bypass). Po hookach (audit-all zdąży
        # zalogować próbę), przed bramką/wykonaniem. deny>allow egzekwuje RuleSet.
        if self.gate.evaluate_rules(name, args, is_mcp=is_mcp) == "deny":
            note = (f"Blocked by a permission rule (deny) for '{name}'. This action is "
                    "not permitted by the current allow/deny rules.")
            self.emit({"type": "tool_result", "id": call_id, "ok": False,
                       "summary": "Blocked by permission rule"})
            self.history.append({"role": "tool", "tool_call_id": call_id, "content": note})
            return

        # M13: tryby accept-edits/bypass pomijają dialog dla odpowiednich narzędzi
        # (zmiany nadal trafiają do checkpointów → „Undo" działa). Komendy z metaznakami
        # i tak odrzuci execute_tool (P0-1).
        if mutating and not self._auto_approves(name):
            decision = self._gate_mutation(call_id, name, args, is_mcp)
            if decision == "reject":
                self.emit({"type": "tool_result", "id": call_id, "ok": False, "summary": "Rejected by user"})
                self.history.append({"role": "tool", "tool_call_id": call_id, "content": "User rejected this action."})
                return

        # M13-B3: zsnapshotuj oryginał PRZED mutacją (po zatwierdzeniu, przed zapisem),
        # by „Undo" mógł go odtworzyć. run_command / mutujące MCP → „partial undo".
        self._snapshot_before(name, args, is_mcp=is_mcp, mutating=mutating)

        if is_mcp:
            try:
                result = self.mcp.call_tool(name, args)
            except Exception as exc:  # noqa: BLE001
                result = f"Error: MCP tool failed: {exc}"
        else:
            # P1-B: reguły deny egzekwowane też na WYNIKACH grep/glob/list_dir (nie tylko
            # na argumencie). Domknięcie budowane tylko gdy są reguły i narzędzie przeszukuje
            # → zerowy narzut, gdy ruleset pusty (evaluate_rules i tak short-circuituje).
            rule_filter = None
            if name in ("grep", "glob", "list_dir") and not self.gate.ruleset.empty:
                rule_filter = lambda rel: self.gate.evaluate_rules("read_file", {"path": rel}) == "deny"  # noqa: E731
            result = execute_tool(
                self.ws, name, args,
                on_output=lambda chunk: self.emit({"type": "output", "id": call_id, "chunk": chunk}),
                stop_flag=stop or (lambda: False),  # P0-4: Stop sesji dociera do run_command
                rule_filter=rule_filter,
            )
        ok = not result.startswith("Error")
        # M14-B5: hook post_tool (np. auto-format po zapisie, log audytu). Nie zmienia wyniku.
        self._run_post_tool_hooks(call_id, name, args, ok, result)
        self.emit({"type": "tool_result", "id": call_id, "ok": ok, "summary": result[:600]})
        self.history.append({"role": "tool", "tool_call_id": call_id, "content": result})
        # M19-B3: pasywna diagnostyka po udanej edycji pliku (jak Grok CLI). Best-effort.
        if ok and not is_mcp and name in ("write_file", "edit_file"):
            self._emit_diagnostics(args.get("path"))

    def _handle_delegate(self, call_id: str, args: dict) -> None:
        """M17-B2: uruchom delegację (subagenci) i oddaj modelowi streszczenia.
        `delegate_fn(tasks)` jest synchroniczne (blokuje turę orkiestratora, która i
        tak biegnie w wątku-workerze) i zwraca tekst streszczeń."""
        tasks = args.get("tasks")
        if not isinstance(tasks, list) or not tasks:
            note = "Error: delegate requires a non-empty 'tasks' array of {role, task}."
            self.emit({"type": "tool_result", "id": call_id, "ok": False, "summary": note})
            self.history.append({"role": "tool", "tool_call_id": call_id, "content": note})
            return
        try:
            summary = self._delegate_fn(tasks)  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001
            summary = f"Error: delegation failed: {exc}"
        ok = not str(summary).startswith("Error")
        self.emit({"type": "tool_result", "id": call_id, "ok": ok, "summary": str(summary)[:600]})
        self.history.append({"role": "tool", "tool_call_id": call_id, "content": str(summary)})

    def _handle_lsp(self, call_id: str, args: dict) -> None:
        """M19-B3: zapytanie do serwera języka (READONLY). Ścieżka sandboxowana przez
        Workspace.resolve; wynik (Location/hover/symbole) wraca do modelu jako JSON."""
        mgr = self._lsp()
        if mgr is None:
            note = "LSP is not available (no language server configured for this workspace)."
            self.emit({"type": "tool_result", "id": call_id, "ok": False, "summary": note})
            self.history.append({"role": "tool", "tool_call_id": call_id, "content": note})
            return
        action = args.get("action") or "hover"
        try:
            p = self.ws.resolve(args.get("path") or "")
        except Exception:  # noqa: BLE001 (WorkspaceError — ucieczka poza workspace)
            note = f"Invalid path: {args.get('path')!r}"
            self.emit({"type": "tool_result", "id": call_id, "ok": False, "summary": note})
            self.history.append({"role": "tool", "tool_call_id": call_id, "content": note})
            return
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            text = ""
        try:
            result = mgr.query(action, str(p), text,
                               int(args.get("line") or 0), int(args.get("character") or 0))
            out = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
            if not out or out == "null":
                out = "No result."
            ok = not out.startswith("Error")
        except Exception as exc:  # noqa: BLE001
            out, ok = f"Error: LSP query failed: {exc}", False
        self.emit({"type": "tool_result", "id": call_id, "ok": ok, "summary": out[:600]})
        self.history.append({"role": "tool", "tool_call_id": call_id, "content": out})

    def _handle_web_search(self, call_id: str, args: dict,
                           stop: Optional[Callable[[], bool]] = None) -> None:
        """Faza-G/TOP1: live web/X search (READONLY — bez bramki). Reużywa
        `tools.web_search` (silnik `responses_client`); zwraca syntezę + cytowania do modelu
        jako wynik narzędzia. Jak `lsp`, biegnie bez zatwierdzenia (czysto czytające).
        Off-switch (`config.WEB_SEARCH_ENABLED`) zwykle ukrywa narzędzie; tu twardo odmawiamy,
        gdyby model zawołał je mimo to (np. z historii) — by wyłączenie realnie blokowało."""
        if not getattr(config, "WEB_SEARCH_ENABLED", False):
            note = "web_search is disabled."
            self.emit({"type": "tool_result", "id": call_id, "ok": False, "summary": note})
            self.history.append({"role": "tool", "tool_call_id": call_id, "content": note})
            return
        sources = args.get("sources") if isinstance(args.get("sources"), list) else None
        out = web_search(
            args.get("query") or "", api_key_provider=self.api_key_provider,
            base=self.base_url, model=self._cur_model, sources=sources,
            stop_flag=stop or (lambda: False),
        )
        ok = not out.startswith("Error")
        self.emit({"type": "tool_result", "id": call_id, "ok": ok, "summary": out[:600]})
        self.history.append({"role": "tool", "tool_call_id": call_id, "content": out})

    def _handle_update_plan(self, call_id: str, args: dict) -> None:
        """Faza-G/TOP3: zapisz/odśwież live checklist zadania (jak TodoWrite) i wyemituj
        ramkę `plan` do renderera (AgentPanel). META — nic nie mutuje, biegnie bez bramki.
        Pełna lista przychodzi za każdym razem (zastąpienie), więc renderer tylko podmienia.
        Wynik `tool` (potwierdzenie) wraca do modelu, by historia była zbalansowana."""
        items = normalize_plan(args.get("steps"))
        self.emit({"type": "plan", "items": items})
        summary = plan_summary(items)
        self.emit({"type": "tool_result", "id": call_id, "ok": True, "summary": summary})
        self.history.append({"role": "tool", "tool_call_id": call_id, "content": summary})

    def _emit_diagnostics(self, path: Optional[str]) -> None:
        """M19-B3: po edycie pliku poślij ramkę `diagnostics` (best-effort). No-op gdy
        LSP wyłączone / brak serwera dla rozszerzenia. Nigdy nie wywraca tury."""
        mgr = self._lsp()
        if mgr is None or not path:
            return
        try:
            p = self.ws.resolve(path)
            items = mgr.diagnostics(str(p), p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return
        self.emit({"type": "diagnostics", "path": p.as_posix(), "items": items or []})

    def _accumulate_usage(self, usage: Optional[dict]) -> None:
        """M17-B6: dolicz tokeny z `usage` LLM (gdy serwer je zwrócił). Tolerancyjne
        na warianty pól (prompt/input, completion/output)."""
        if not isinstance(usage, dict):
            return
        inp = usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0
        out = usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0
        try:
            self.usage["input_tokens"] += int(inp)
            self.usage["output_tokens"] += int(out)
            # Realny rozmiar ostatniego promptu (= bieżące okno kontekstowe) > szacunek.
            if int(inp) > 0:
                self.last_input_tokens = int(inp)
        except (TypeError, ValueError):
            pass

    @staticmethod
    def _estimate_tokens(messages: List[dict]) -> int:
        """Zgrubny szacunek tokenów promptu (~4 znaki/token) — do miernika okna
        kontekstowego, gdy serwer nie zwraca `usage`. Liczymy tekst i argumenty
        `tool_calls`; bloki obrazów (data-URI) pomijamy (liczą się inaczej, a dokładnego
        licznika i tak nie mamy bez API)."""
        chars = 0
        for m in messages:
            c = m.get("content")
            if isinstance(c, str):
                chars += len(c)
            elif isinstance(c, list):
                for part in c:
                    if isinstance(part, dict) and part.get("type") == "text":
                        chars += len(part.get("text") or "")
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                chars += len(fn.get("name") or "") + len(fn.get("arguments") or "")
        return chars // 4

    def context_tokens(self) -> int:
        """Bieżące zajęcie okna kontekstowego: realne (usage.input z ostatniego
        wywołania) gdy dostępne, inaczej szacunek (~4 znaki/token)."""
        return self.last_input_tokens or self.last_context_tokens

    def _emit_usage(self) -> None:
        """Live miernik tokenów/okna kontekstowego (ramka `usage`). Emitowany po każdym
        wywołaniu LLM w turze, więc panel aktualizuje się NA BIEŻĄCO — nie czeka na koniec
        tury. `max_context` z modelu tury (szacunek z config). Tolerancyjny na błędy."""
        try:
            self.emit({
                "type": "usage",
                "input_tokens": int(self.usage.get("input_tokens", 0) or 0),
                "output_tokens": int(self.usage.get("output_tokens", 0) or 0),
                "context_tokens": int(self.context_tokens() or 0),
                "max_context": config.context_window_for(self._cur_model),
            })
        except Exception:  # noqa: BLE001
            pass

    def _gate_mutation(self, call_id: str, name: str, args: dict, is_mcp: bool) -> str:
        """Bramka zatwierdzenia mutacji. Zwraca 'accept'/'reject'/'always' (lub 'accept'
        gdy już dopuszczone). Obsługuje plikowe (preview diff/komenda) i MCP (karta
        narzędzia). Komendy z metaznakami pomijają dialog — execute_tool je odrzuci (P0-1)."""
        # M19-B4: reguła allow (glob) auto-akceptuje mutację. NIGDY nie obchodzi P0-1:
        # run_command z metaznakami NIE może być dopuszczona regułą — spada niżej, gdzie
        # execute_tool ją odrzuci. (deny obsłużone wcześniej w _handle_tool_call.)
        if self.gate.evaluate_rules(name, args, is_mcp=is_mcp) == "allow":
            if not (name == "run_command" and command_metachars(args.get("command") or "")):
                return "accept"
        if is_mcp:
            key = f"mcp:{name}"
            if not self.gate.needs_approval_key(key):
                return "accept"
            detail = self._mcp_detail(name, args)
            decision = self.request_approval(call_id, name, detail)
            if decision == "always":
                self.gate.allow_key(key)
            return decision
        # narzędzia plikowe (write/edit/run) — dotychczasowa logika
        if not self.gate.needs_approval(name, args):
            return "accept"
        # P0-1: run_command z metaznakami nie da się dopuścić — pomiń dialog,
        # execute_tool odrzuci jednym autorytatywnym komunikatem (model dostanie poprawkę).
        if name == "run_command" and command_metachars(args.get("command") or ""):
            return "accept"
        detail = preview_change(self.ws, name, args)
        decision = self.request_approval(call_id, name, detail)
        if decision == "always":
            self.gate.allow(name, args)
        return decision

    def _mcp_detail(self, name: str, args: dict) -> dict:
        """Opis wywołania narzędzia MCP do karty zatwierdzenia (M14-F2)."""
        try:
            info = self.mcp.describe_tool(name)
        except Exception:  # noqa: BLE001
            info = {"name": name, "server_id": "", "description": ""}
        return {
            "kind": "mcp_tool_call",
            "qualified_name": name,
            "tool": info.get("name") or name,
            "server": info.get("server_id") or "",
            "description": info.get("description") or "",
            "args": args,
        }

    # --- hooki (M14-B5); no-op gdy self.hooks is None ---
    def _run_pre_tool_hooks(self, call_id: str, name: str, args: dict) -> Optional[str]:
        """Uruchom hooki pre_tool. Zwraca komunikat blokady (str) gdy któryś zablokował,
        inaczej None. Błąd hooka nie wywraca tury (deterministyczny, ale izolowany)."""
        if self.hooks is None:
            return None
        try:
            return self.hooks.run_pre_tool(name, args, workspace=self.ws, emit=self.emit)
        except Exception:  # noqa: BLE001
            return None

    def _run_post_tool_hooks(self, call_id: str, name: str, args: dict, ok: bool, result: str) -> None:
        if self.hooks is None:
            return
        try:
            self.hooks.run_post_tool(name, args, ok=ok, result=result, workspace=self.ws, emit=self.emit)
        except Exception:  # noqa: BLE001
            pass

    def _snapshot_before(self, name: str, args: dict, *, is_mcp: bool = False,
                         mutating: bool = False) -> None:
        """M13-B3: zapisz oryginał edytowanego pliku do checkpointu (write/edit) albo
        oznacz turę jako uruchamiającą komendę (run_command/mutujące MCP → undo
        częściowy — efektów poza workspace nie da się zsnapshotować). Nigdy nie
        wywraca tury — błąd checkpointu jest połykany."""
        cp = self._checkpoints()
        if cp is None:
            return
        try:
            if is_mcp:
                if mutating:
                    cp.mark_command()  # skutki MCP poza workspace → „partial undo"
            elif name in ("write_file", "edit_file"):
                path = args.get("path")
                if path:
                    cp.snapshot(path)
            elif name == "run_command":
                cp.mark_command()
        except Exception:  # noqa: BLE001
            pass
