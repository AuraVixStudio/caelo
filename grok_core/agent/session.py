"""Pętla agenta kodowania.

Sterowana zdarzeniami: każdy krok (tekst modelu, wywołanie narzędzia, prośba o
zgodę, wynik narzędzia) jest emitowany przez callback `emit`, a `request_approval`
blokuje do czasu decyzji użytkownika. `llm_fn` jest wstrzykiwany (test = mock).
"""

from __future__ import annotations

import json
from typing import Callable, List, Optional

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
    ) -> None:
        self.ws = workspace
        self.gate = gate
        self.llm_fn = llm_fn
        self.api_key_provider = api_key_provider
        self.base_url = base_url
        self.emit = emit
        self.request_approval = request_approval
        self.max_iters = max_iters
        self.history: List[dict] = []

    def run_turn(self, user_text: str, model: str, temperature: float = 0.2,
                 stop_flag: Optional[Callable[[], bool]] = None,
                 images: Optional[List[str]] = None) -> None:
        stop = stop_flag or (lambda: False)
        if images:
            # Treść multimodalna: tekst + załączone obrazy (data-URI / URL).
            content: object = [{"type": "text", "text": user_text}] + [
                {"type": "image_url", "image_url": {"url": u}} for u in images
            ]
        else:
            content = user_text
        self.history.append({"role": "user", "content": content})

        for _ in range(self.max_iters):
            if stop():
                self.emit({"type": "stopped"})
                return
            # self.history jest jedynym źródłem prawdy (P0-5) — budujemy z niego
            # `messages` co iterację, by zawsze zawierało odpowiedzi `tool`.
            messages = [{"role": "system", "content": SYSTEM_PROMPT}] + self.history
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

        if name in MUTATING and self.gate.needs_approval(name, args):
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

        result = execute_tool(
            self.ws, name, args,
            on_output=lambda chunk: self.emit({"type": "output", "id": call_id, "chunk": chunk}),
            stop_flag=stop or (lambda: False),  # P0-4: Stop sesji dociera do run_command
        )
        ok = not result.startswith("Error")
        self.emit({"type": "tool_result", "id": call_id, "ok": ok, "summary": result[:600]})
        self.history.append({"role": "tool", "tool_call_id": call_id, "content": result})
