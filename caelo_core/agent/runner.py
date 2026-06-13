"""Transport-neutralny runner agenta kodowania (M19-§0).

Wydziela budowę i prowadzenie `AgentSession` (z checkpointami / MCP / hookami /
skillami / delegacją subagentów) z handlera WebSocket `routes/agent.py`, by ten
SAM kod okablowania mógł obsłużyć WS, tryb headless (M19-B1) i ACP (M19-B2).
Transporty różni tylko: `emit(dict)` (sink ramek), `request_approval(id, name,
detail) -> str` i `stop() -> bool`.

Refaktor zachowawczy: logika identyczna jak dotąd w `routes/agent.py` (leniwa
`AgentSession`, leniwy `TeamManager`, `delegate_fn`, zapis tury do historii huba —
M9-B2). Warstwa transportu (flaga zajętości, słownik `pending`, ramka `done`,
czyszczenie `stop`) zostaje w handlerze — runner jej nie zna.

`emit` runnera opakowuje `emit` transportu: łapie finalną odpowiedź tury z ramki
`assistant_done` najwyższego poziomu (subagenci są opakowani w `subagent`, więc ich
wewnętrzne `assistant_done` nie nadpiszą odpowiedzi orkiestratora — jak dotąd).
"""

from __future__ import annotations

import logging
import secrets
from typing import Callable, List, Optional

import config  # type: ignore  # repo-root (sys.path z caelo_core/__init__.py)

from caelo_core.agent.session import AgentSession

log = logging.getLogger(__name__)

Emit = Callable[[dict], None]
RequestApproval = Callable[[str, str, Optional[dict]], str]  # (id, name, detail) -> decision
Stop = Callable[[], bool]


class AgentRunner:
    """Prowadzi tury agenta dla dowolnego transportu. Trzyma leniwą sesję, leniwy
    `TeamManager` oraz model/tryb bieżącej tury (czytane przez `delegate_fn`)."""

    def __init__(self, backend, *, emit: Emit, request_approval: RequestApproval,
                 stop: Stop, tool_names: Optional[set] = None,
                 max_iters: Optional[int] = None, allow_delegate: bool = True,
                 initial_history: Optional[List[dict]] = None,
                 reasoning_effort: Optional[str] = None,
                 session_id: Optional[str] = None) -> None:
        self.backend = backend
        self._emit_transport = emit
        self.request_approval = request_approval
        self.stop = stop
        self._session: Optional[AgentSession] = None
        self._team = None
        # M17: model/tryb bieżącej tury — świeże per tura (delegate_fn ich używa).
        self._model = ""
        self._mode = "ask"
        # M19-B9: poziom reasoning_effort — domyślny (konstruktor, np. headless --effort)
        # + efektywny per tura (`run_turn(reasoning_effort=…)`, np. selektor UI agenta).
        self._reasoning_effort = reasoning_effort
        self._effort = reasoning_effort
        # M9-B2: finalna odpowiedź tury (do zapisu w historii huba).
        self._last_assistant = ""
        # M19-B1: opcje transportów nie-WS (headless/ACP). Domyślne = zachowanie WS:
        #   tool_names=None (wszystkie narzędzia), max_iters=None (default sesji = 25),
        #   allow_delegate=True (orkiestrator deleguje), initial_history=None (świeża).
        self._tool_names = set(tool_names) if tool_names is not None else None
        self._max_iters = max_iters
        self._allow_delegate = allow_delegate
        self._initial_history = initial_history
        # M21: id trwałej sesji (WS ją generuje na połączeniu; headless zapisuje sam,
        # więc tworzy runner bez session_id → `_persist_session` jest no-opem). Gdy
        # ustawione, każda tura zapisuje pełną historię do `agent/sessions.py`.
        self._session_id = session_id

    @property
    def last_assistant(self) -> str:
        return self._last_assistant

    @property
    def current_session_id(self) -> Optional[str]:
        """Id trwałej sesji prowadzonej przez ten runner (None = sesja nieutrwalana)."""
        return self._session_id

    def new_session(self, session_id: Optional[str] = None) -> str:
        """M21: rozpocznij NOWĄ sesję — porzuć bieżącą `AgentSession` (świeża historia),
        wygeneruj/ustaw id. Zwraca aktywne `session_id`. Workspace/projekt bez zmian."""
        self._session = None
        self._initial_history = None
        self._last_assistant = ""
        self._session_id = session_id or secrets.token_urlsafe(8)
        return self._session_id

    def resume_session(self, session_id: str, history: List[dict]) -> None:
        """M21: wznów sesję `session_id` z zapisaną historią — wstrzyknięta przed
        1. turą (`_ensure_session`), więc model kontynuuje z pełnym kontekstem."""
        self._session = None
        self._initial_history = list(history or [])
        self._last_assistant = ""
        self._session_id = session_id

    @property
    def history(self) -> List[dict]:
        """Historia bieżącej sesji (do utrwalenia/wznowienia w headless/ACP)."""
        return self._session.history if self._session is not None else []

    @property
    def usage(self) -> dict:
        """M17-B6: skumulowane tokeny sesji orkiestratora (`input_tokens`/`output_tokens`)
        + miernik okna kontekstowego (`context_tokens` = bieżące zajęcie, `max_context` =
        przybliżony limit modelu tury). Transport WS emituje je po turze do panelu agenta.
        Brak sesji / mock bez `usage` → zera."""
        sess = self._session
        out = {"input_tokens": 0, "output_tokens": 0, "context_tokens": 0,
               "max_context": config.context_window_for(self._model)}
        if sess is None:
            return out
        u = sess.usage
        if isinstance(u, dict):
            out["input_tokens"] = int(u.get("input_tokens", 0) or 0)
            out["output_tokens"] = int(u.get("output_tokens", 0) or 0)
        try:
            out["context_tokens"] = int(sess.context_tokens() or 0)
        except Exception:  # noqa: BLE001
            pass
        return out

    def emit(self, ev: dict) -> None:
        """Sink ramek: łapie finalną odpowiedź tury (M9-B2), potem przekazuje do
        transportu. Tylko `assistant_done` najwyższego poziomu (subagenci opakowani)."""
        if ev.get("type") == "assistant_done":
            self._last_assistant = ev.get("content") or ""
        self._emit_transport(ev)

    def _get_team(self):
        """Leniwy TeamManager (M17). Współdzieli emit/approval/stop orkiestratora;
        scalenia rejestruje w magazynie Backendu (REST je stosuje)."""
        if self._team is None:
            from caelo_core.agent.llm import stream_chat_with_tools
            from caelo_core.agent.team import TeamManager

            self._team = TeamManager(
                registry=self.backend.subagents, gate=self.backend.permissions,
                llm_fn=stream_chat_with_tools, api_key_provider=self.backend.get_api_key,
                base_url=config.API_BASE, mcp=self.backend.mcp, hooks=self.backend.hooks,
                emit=self.emit, request_approval=self.request_approval,
                orchestrator_stop=self.stop, merges_provider=self.backend.get_team_merges,
                on_report=self.backend.record_team_report,
            )
        return self._team

    def _delegate_fn(self, tasks: list) -> str:
        ws_obj = self.backend.get_workspace()
        if ws_obj is None:
            return "Error: no workspace selected for delegation"
        team = self._get_team()
        return team.run(tasks, model=self._model, workspace=ws_obj, mode=self._mode,
                        reasoning_effort=self._effort)

    def _ensure_session(self, ws_obj) -> AgentSession:
        session = self._session
        if session is None:
            from caelo_core.agent.llm import stream_chat_with_tools

            extra = {"max_iters": self._max_iters} if self._max_iters else {}
            session = AgentSession(
                ws_obj, self.backend.permissions, stream_chat_with_tools,
                self.backend.get_api_key, config.API_BASE,
                emit=self.emit, request_approval=self.request_approval,
                checkpoints_provider=self.backend.get_checkpoints,  # M13-B3/B5
                mcp=self.backend.mcp,        # M14-B2: narzędzia MCP w agencie
                hooks=self.backend.hooks,    # M14-B5: hooki cyklu życia narzędzi
                skills=self.backend.skills,  # M14-B6: wstrzykiwanie skilli do promptu
                # M19-B1: delegacja wyłączalna (--disallowed-tools Agent); zawężenie
                # narzędzi (--tools/--disallowed-tools) przez tool_names roli M17-B1.
                delegate_fn=(self._delegate_fn if self._allow_delegate else None),
                tool_names=self._tool_names,
                # M19-B3: dostawca LSP (getattr — atrapy backendu bez get_lsp → None).
                lsp_provider=getattr(self.backend, "get_lsp", None),
                # M19-B8: pamięć hybrydowa (getattr — atrapy backendu bez memory → None).
                memory=getattr(self.backend, "memory", None),
                # M19-B9: domyślny effort sesji (per-tura nadpisywany w run_turn).
                reasoning_effort=self._reasoning_effort,
                **extra,
            )
            # M19-B1: wznowiona sesja (headless -s/-c/ACP session/load) — wstrzyknij
            # historię PRZED pierwszą turą (run_turn dopisze do niej user message).
            if self._initial_history:
                session.history = list(self._initial_history)
            self._session = session
        else:
            session.ws = ws_obj  # workspace mógł się zmienić
        return session

    def run_turn(self, text: str, model: str, *, images: Optional[List[str]] = None,
                 mode: str = "ask", reasoning_effort: Optional[str] = None) -> str:
        """Uruchom jedną turę agenta. Zwraca finalną odpowiedź (`last_assistant`) i
        zapisuje turę do historii huba (M9-B2). Błąd tury → ramka `error` (jak WS;
        P1-13: bez surowego str(exc)). Transport zarządza busy/done wokół wywołania;
        `stop` jest tylko czytany — czyszczenie należy do transportu. M19-B9:
        `reasoning_effort` (None = domyślny runnera) trafia do sesji i delegacji."""
        self._last_assistant = ""
        ran = False  # 3.3-e: czy tura faktycznie ruszyła (był workspace) — gate na record_event
        try:
            ws_obj = self.backend.get_workspace()
            if ws_obj is None:
                self.emit({"type": "error", "error": "No workspace selected"})
                return ""
            session = self._ensure_session(ws_obj)
            ran = True
            # M17: zapamiętaj model/tryb tury — delegate_fn użyje ich dla subagentów.
            self._model = model
            self._mode = mode
            # M19-B9: efektywny effort tej tury (per-tura nadpisuje domyślny runnera) —
            # używany przez delegate_fn dla subagentów bez własnego effortu roli.
            self._effort = reasoning_effort if reasoning_effort is not None else self._reasoning_effort
            session.run_turn(text, model, stop_flag=self.stop, images=images or [],
                             mode=mode, reasoning_effort=reasoning_effort)
        except Exception:  # noqa: BLE001
            # P1-13: nie wysyłaj surowego str(exc) (może zawierać szczegóły xAI/ścieżki).
            log.exception("Agent turn failed")
            self.emit({"type": "error", "error": "Agent error (see server log for details)"})
        finally:
            # M9-B2: podsumowanie tury do wspólnej historii huba (mode=code). Tekst =
            # finalna odpowiedź agenta; instrukcja usera + workspace w meta.
            # 3.3-e: tylko gdy tura RUSZYŁA (był workspace) — inaczej `text` (prompt) jest
            # truthy i record_event zapisywał pusty event 'code' (workspace=None) za turę,
            # która się nie wykonała (śmieci w historii + indeksie pamięci).
            if ran and (text or self._last_assistant):
                wsp = self.backend.get_workspace()
                self.backend.record_event(
                    mode="code", text=self._last_assistant or "",
                    meta={"prompt": text, "model": model,
                          "workspace": wsp.root.as_posix() if wsp else None},
                )
            # M21: utrwal PEŁNĄ sesję (do wznowienia) — osobno od M9 (wyszukiwalny log).
            # No-op gdy runner nie prowadzi trwałej sesji (np. headless zapisuje sam).
            self._persist_session(model)
        return self._last_assistant

    def _persist_session(self, model: str) -> None:
        """M21: zapisz historię bieżącej sesji do `agent/sessions.py` (best-effort,
        nigdy nie wywraca tury). Stempluje project_id aktywnego projektu (M9-B5)."""
        if not self._session_id or self._session is None:
            return
        try:
            from caelo_core.agent import sessions

            wsp = self.backend.get_workspace()
            sessions.save(
                id=self._session_id,
                cwd=wsp.root.as_posix() if wsp else "",
                history=self._session.history,
                project_id=getattr(self.backend, "current_project_id", None),
                model=model,
            )
        except Exception:  # noqa: BLE001
            log.warning("Could not persist agent session", exc_info=True)
