"""Pętla agenta kodowania.

Sterowana zdarzeniami: każdy krok (tekst modelu, wywołanie narzędzia, prośba o
zgodę, wynik narzędzia) jest emitowany przez callback `emit`, a `request_approval`
blokuje do czasu decyzji użytkownika. `llm_fn` jest wstrzykiwany (test = mock).
"""

from __future__ import annotations

import json
from typing import Callable, List, Optional

import config  # type: ignore  # repo-root (sys.path z grok_core/__init__.py)

from grok_core.agent.grokmd import build_system_prompt
from grok_core.agent.permissions import MUTATING, PermissionGate, command_metachars
from grok_core.agent.tools import TOOLS, execute_tool, preview_change
from grok_core.agent.workspace import Workspace

SYSTEM_PROMPT = (
    "You are Grok Code, an agentic coding assistant working in the user's local workspace.\n"
    "You can read, search, write and edit files, and run shell commands via tools.\n"
    "Guidelines:\n"
    "- Explore with read_file/list_dir/glob/grep before changing anything.\n"
    "- Prefer edit_file with a unique old_string; use write_file for new files.\n"
    "- Keep changes minimal and focused on the request.\n"
    "- All paths are relative to the workspace root.\n"
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
        max_iters: int = 25,
        checkpoints_provider: Optional[Callable[[], object]] = None,
        grok_md_global_dir: Optional[str] = None,
    ) -> None:
        self.ws = workspace
        self.gate = gate
        self.llm_fn = llm_fn
        self.api_key_provider = api_key_provider
        self.base_url = base_url
        self.emit = emit
        self.request_approval = request_approval
        self.max_iters = max_iters
        # M13-B3: dostawca menedżera checkpointów (współdzielony z REST przez Backend);
        # None → checkpointy wyłączone (np. w self-checkach starej ścieżki).
        self.checkpoints_provider = checkpoints_provider
        # M13-B4: katalog globalnego GROK.md (domyślnie config.DATA_DIR).
        self.grok_md_global_dir = grok_md_global_dir
        self.history: List[dict] = []
        self._mode = DEFAULT_MODE  # M13: tryb bieżącej tury (ask/accept-edits/plan/bypass)

    def _checkpoints(self):
        if not self.checkpoints_provider:
            return None
        try:
            return self.checkpoints_provider()
        except Exception:  # noqa: BLE001
            return None

    def _build_system_prompt(self) -> str:
        """M13-B4: bazowy prompt + reguły GROK.md (workspace nadpisuje global) +
        (M13-B2) instrukcja trybu planowania. Liczone per tura (workspace może się
        zmienić, plik GROK.md mógł zostać zedytowany)."""
        global_dir = self.grok_md_global_dir or getattr(config, "DATA_DIR", None)
        ws_root = self.ws.root if self.ws else None
        prompt = build_system_prompt(SYSTEM_PROMPT, ws_root, global_dir)
        if self._mode == "plan":
            prompt += PLAN_MODE_PROMPT
        return prompt

    def _auto_approves(self, name: str) -> bool:
        """M13: czy bieżący tryb pomija dialog zatwierdzenia dla narzędzia `name`.
        bypass → wszystko; accept-edits → tylko write/edit (komendy nadal pytane)."""
        if self._mode == "bypass":
            return True
        if self._mode == "accept-edits" and name in ("write_file", "edit_file"):
            return True
        return False

    def run_turn(self, user_text: str, model: str, temperature: float = 0.2,
                 stop_flag: Optional[Callable[[], bool]] = None,
                 images: Optional[List[str]] = None, mode: str = DEFAULT_MODE) -> None:
        stop = stop_flag or (lambda: False)
        self._mode = mode if mode in AGENT_MODES else DEFAULT_MODE
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

        system_prompt = self._build_system_prompt()  # M13-B4: GROK.md + (B2) plan mode
        for _ in range(self.max_iters):
            if stop():
                self.emit({"type": "stopped"})
                return
            # self.history jest jedynym źródłem prawdy (P0-5) — budujemy z niego
            # `messages` co iterację, by zawsze zawierało odpowiedzi `tool`.
            messages = [{"role": "system", "content": system_prompt}] + self.history
            assistant = self.llm_fn(
                self.api_key_provider(), self.base_url, messages, model, temperature, TOOLS,
                on_text=lambda full: self.emit({"type": "text", "full": full}),
                stop_flag=stop,
            )
            self.history.append(assistant)

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
                try:
                    self._handle_tool_call(tc, stop)
                except Exception as exc:  # noqa: BLE001
                    # Błąd obsługi narzędzia nie może zostawić wiadomości assistant
                    # z nieodpowiedzianymi tool_calls (następny request → 400).
                    self._finalize_interrupted(tool_calls[idx:], reason="error during tool execution")
                    self.emit({"type": "error", "error": str(exc)})
                    return

        self.emit({"type": "error", "error": "Max iterations reached"})

    def _finalize_interrupted(self, pending: List[dict], reason: str = "interrupted") -> None:
        """P0-5: dopisz syntetyczny wynik `tool` dla każdego nieobsłużonego
        `tool_call`. Wiadomość `assistant` z N `tool_calls` MUSI mieć N odpowiedzi
        `tool` (kontrakt xAI/OpenAI) — inaczej następny request zwraca 400."""
        for tc in pending:
            fn = tc.get("function", {}) or {}
            call_id = tc.get("id") or fn.get("name", "")
            self.emit({"type": "tool_result", "id": call_id, "ok": False, "summary": reason})
            self.history.append({"role": "tool", "tool_call_id": call_id, "content": reason})

    def _handle_tool_call(self, tc: dict, stop: Optional[Callable[[], bool]] = None) -> None:
        fn = tc.get("function", {}) or {}
        name = fn.get("name", "")
        call_id = tc.get("id") or name
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except Exception:
            args = {}

        self.emit({"type": "tool_call", "id": call_id, "name": name, "args": args})

        # M13-B2: w trybie planowania mutacje są wyłączone — odpowiedz modelowi
        # czytelnym komunikatem (kontynuuje planowanie), nie wykonuj narzędzia.
        if self._mode == "plan" and name in MUTATING:
            note = (f"Blocked in plan mode: '{name}' is disabled until the plan is "
                    "approved. Keep using read-only tools and finish the plan.")
            self.emit({"type": "tool_result", "id": call_id, "ok": False,
                       "summary": "Blocked in plan mode"})
            self.history.append({"role": "tool", "tool_call_id": call_id, "content": note})
            return

        # M13: tryby accept-edits/bypass pomijają dialog dla odpowiednich narzędzi
        # (zmiany nadal trafiają do checkpointów → „Undo" działa). Komendy z metaznakami
        # i tak odrzuci execute_tool (P0-1).
        if name in MUTATING and not self._auto_approves(name) and self.gate.needs_approval(name, args):
            # P0-1: komend run_command z metaznakami powłoki nie da się dopuścić
            # ani „Always allow" — pomiń dialog i pozwól, by execute_tool odrzucił
            # ją jednym, autorytatywnym komunikatem (model dostanie poprawkę).
            dangerous = name == "run_command" and command_metachars(args.get("command") or "")
            if not dangerous:
                detail = preview_change(self.ws, name, args)
                decision = self.request_approval(call_id, name, detail)
                if decision == "reject":
                    self.emit({"type": "tool_result", "id": call_id, "ok": False, "summary": "Rejected by user"})
                    self.history.append({"role": "tool", "tool_call_id": call_id, "content": "User rejected this action."})
                    return
                if decision == "always":
                    self.gate.allow(name, args)

        # M13-B3: zsnapshotuj oryginał PRZED mutacją (po zatwierdzeniu, przed zapisem),
        # by „Undo" mógł go odtworzyć. run_command → oznacz turę jako „partial undo".
        self._snapshot_before(name, args)

        result = execute_tool(
            self.ws, name, args,
            on_output=lambda chunk: self.emit({"type": "output", "id": call_id, "chunk": chunk}),
            stop_flag=stop or (lambda: False),  # P0-4: Stop sesji dociera do run_command
        )
        ok = not result.startswith("Error")
        self.emit({"type": "tool_result", "id": call_id, "ok": ok, "summary": result[:600]})
        self.history.append({"role": "tool", "tool_call_id": call_id, "content": result})

    def _snapshot_before(self, name: str, args: dict) -> None:
        """M13-B3: zapisz oryginał edytowanego pliku do checkpointu (write/edit) albo
        oznacz turę jako uruchamiającą komendę (run_command → undo częściowy). Nigdy
        nie wywraca tury — błąd checkpointu jest połykany."""
        cp = self._checkpoints()
        if cp is None:
            return
        try:
            if name in ("write_file", "edit_file"):
                path = args.get("path")
                if path:
                    cp.snapshot(path)
            elif name == "run_command":
                cp.mark_command()
        except Exception:  # noqa: BLE001
            pass
