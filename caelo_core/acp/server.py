"""Serwer ACP (Agent Client Protocol) po stdio (M19-B2).

`python -m caelo_core acp` → agent kodowania jako serwer ACP (JSON-RPC 2.0 po stdin/
stdout, newline-delimited, UTF-8) dla Zed/Neovim/Emacs/marimo. Reużywa `AgentRunner`
(M19-§0) — to samo okablowanie sesji co WS/headless, inny transport.

Dyscyplina stdout: notyfikacje/odpowiedzi JSON-RPC; logi na stderr (BRAK linii handshake).
Wątkowość: wątek-czytnik (stdin) dyspozycjonuje wiadomości; `session/prompt` biegnie w
WĄTKU-WORKERZE (blokujące LLM) i sam wysyła finalny `result`. Serwer JEST też klientem dla
`session/request_permission` (żądanie agent→klient) — odpowiedzi korelowane po `id` (jak
`McpClient`). Zapis na stdout pod jednym lockiem (jak `StdioTransport`).
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import sys
import threading
from typing import Optional

from caelo_core.acp.bridge import frame_to_acp, stop_reason

log = logging.getLogger("caelo_core.acp")

PROTOCOL_VERSION = 1
APPROVAL_TIMEOUT_S = 600  # jak WS — limit oczekiwania na decyzję klienta (fail-closed po nim)


class _Session:
    def __init__(self, sid: str, cwd: str) -> None:
        self.sid = sid
        self.cwd = cwd
        self.runner = None  # AgentRunner — leniwie w _make_session
        self.stop = threading.Event()
        self.text_state: dict = {"prev": 0}
        self.stop_internal: Optional[str] = None
        self.busy = False


class AcpServer:
    def __init__(self, backend) -> None:
        self.backend = backend
        self._sessions: dict[str, _Session] = {}
        self._write_lock = threading.Lock()
        # Współdzielony workspace Backendu → serializuj tury (jeden naraz między sesjami).
        self._turn_lock = threading.Lock()
        self._pending: dict = {}      # id → {event, result} dla żądań agent→klient
        self._id_lock = threading.Lock()
        self._next = 0

    # --- transport ---------------------------------------------------------------
    def _send(self, obj: dict) -> None:
        line = json.dumps(obj, ensure_ascii=False)
        with self._write_lock:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()

    def _send_result(self, req_id, result: dict) -> None:
        self._send({"jsonrpc": "2.0", "id": req_id, "result": result})

    def _send_error(self, req_id, code: int, message: str) -> None:
        self._send({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})

    def _next_id(self) -> str:
        with self._id_lock:
            self._next += 1
            return f"srv-{self._next}"

    def _request_client(self, method: str, params: dict, timeout: float) -> Optional[dict]:
        """Żądanie agent→klient; blokuje wątek-workera aż reader skoreluje odpowiedź po
        `id` (None gdy timeout)."""
        rid = self._next_id()
        event = threading.Event()
        self._pending[rid] = {"event": event, "result": None}
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        if not event.wait(timeout=timeout):
            log.warning("client request %s timed out", method)
        return self._pending.pop(rid, {}).get("result")

    # --- pętla czytnika ----------------------------------------------------------
    def serve(self) -> None:
        for raw in sys.stdin:
            line = raw.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            try:
                self._dispatch(msg)
            except Exception:  # noqa: BLE001
                log.exception("ACP dispatch failed")

    def _dispatch(self, msg: dict) -> None:
        # Odpowiedź na NASZE żądanie (session/request_permission) — koreluj po id.
        if "method" not in msg and "id" in msg and ("result" in msg or "error" in msg):
            slot = self._pending.get(msg.get("id"))
            if slot:
                slot["result"] = msg.get("result")
                slot["event"].set()
            return
        method = msg.get("method")
        req_id = msg.get("id")
        params = msg.get("params") or {}
        if method == "initialize":
            self._on_initialize(req_id, params)
        elif method == "session/new":
            self._on_session_new(req_id, params)
        elif method == "session/load":
            self._on_session_load(req_id, params)
        elif method == "session/prompt":
            self._on_session_prompt(req_id, params)
        elif method == "session/cancel":
            self._on_session_cancel(params)  # notyfikacja (bez id)
        elif req_id is not None:
            self._send_error(req_id, -32601, f"Method not found: {method}")

    # --- metody ------------------------------------------------------------------
    def _on_initialize(self, req_id, params) -> None:
        # Echo protocolVersion (tolerancyjnie — jak reszta wire-formatów w projekcie).
        proto = params.get("protocolVersion", PROTOCOL_VERSION)
        self._send_result(req_id, {
            "protocolVersion": proto,
            "agentCapabilities": {"loadSession": True,
                                  "promptCapabilities": {"image": True, "embeddedContext": True}},
            "authMethods": [],
        })

    def _on_session_new(self, req_id, params) -> None:
        cwd = params.get("cwd") or os.getcwd()
        sid = secrets.token_urlsafe(8)
        try:
            self._make_session(sid, cwd)
        except Exception as exc:  # noqa: BLE001
            self._send_error(req_id, -32000, f"cannot create session: {exc}")
            return
        self._send_result(req_id, {"sessionId": sid})

    def _on_session_load(self, req_id, params) -> None:
        sid = params.get("sessionId")
        cwd = params.get("cwd") or os.getcwd()
        if not sid:
            self._send_error(req_id, -32602, "sessionId required")
            return
        if sid not in self._sessions:
            try:
                self._make_session(sid, cwd)
            except Exception as exc:  # noqa: BLE001
                self._send_error(req_id, -32000, f"cannot load session: {exc}")
                return
        self._send_result(req_id, {})

    def _make_session(self, sid: str, cwd: str) -> None:
        from caelo_core.agent.runner import AgentRunner

        sess = _Session(sid, cwd)

        def emit(ev: dict) -> None:
            notif = frame_to_acp(sid, ev, sess.text_state)
            if notif is not None:
                self._send(notif)
            if ev.get("type") in ("stopped", "error"):
                sess.stop_internal = ev.get("type")

        def request_approval(call_id, name, detail):
            return self._approve_via_client(sid, call_id, name)

        sess.runner = AgentRunner(self.backend, emit=emit, request_approval=request_approval,
                                  stop=sess.stop.is_set)
        self._sessions[sid] = sess

    def _approve_via_client(self, sid: str, call_id: str, name: str) -> str:
        """Mapuj prośbę o zgodę na ACP `session/request_permission`; brak odpowiedzi /
        anulowanie → 'reject' (fail-closed)."""
        options = [
            {"optionId": "allow", "name": "Allow", "kind": "allow_once"},
            {"optionId": "allow_always", "name": "Always allow", "kind": "allow_always"},
            {"optionId": "reject", "name": "Reject", "kind": "reject_once"},
        ]
        res = self._request_client("session/request_permission", {
            "sessionId": sid,
            "toolCall": {"toolCallId": call_id, "title": name, "status": "pending"},
            "options": options,
        }, APPROVAL_TIMEOUT_S)
        outcome = (res or {}).get("outcome") or {}
        if outcome.get("outcome") == "selected":
            return {"allow": "accept", "allow_always": "always",
                    "reject": "reject"}.get(outcome.get("optionId"), "reject")
        return "reject"

    def _on_session_prompt(self, req_id, params) -> None:
        sid = params.get("sessionId")
        sess = self._sessions.get(sid)
        if sess is None:
            self._send_error(req_id, -32602, f"unknown session: {sid}")
            return
        if sess.busy:
            self._send_error(req_id, -32000, "session busy")
            return
        text = _prompt_text(params.get("prompt") or [])
        model = self.backend.read_settings().get("code_model") or "grok-build-0.1"
        sess.busy = True
        sess.stop_internal = None
        sess.text_state["prev"] = 0
        threading.Thread(target=self._run_turn, args=(req_id, sess, text, model),
                         daemon=True).start()

    def _run_turn(self, req_id, sess: _Session, text: str, model: str) -> None:
        try:
            with self._turn_lock:  # współdzielony workspace Backendu
                self.backend.set_workspace(sess.cwd)
                sess.stop.clear()
                sess.runner.run_turn(text, model, mode="ask")
            self._send_result(req_id, {"stopReason": stop_reason(sess.stop_internal)})
        except Exception:  # noqa: BLE001
            log.exception("ACP turn failed")
            self._send_result(req_id, {"stopReason": "refusal"})
        finally:
            sess.busy = False

    def _on_session_cancel(self, params) -> None:
        sess = self._sessions.get(params.get("sessionId"))
        if sess is not None:
            sess.stop.set()


def _prompt_text(blocks) -> str:
    parts = []
    for b in blocks:
        if isinstance(b, dict) and b.get("type") == "text":
            parts.append(b.get("text") or "")
        elif isinstance(b, str):
            parts.append(b)
    return "\n".join(p for p in parts if p)


def serve() -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    from caelo_core.state import Backend

    backend = Backend()
    server = AcpServer(backend)
    try:
        server.serve()
    finally:
        try:
            backend.shutdown()  # tree-kill ewentualnych podprocesów MCP
        except Exception:  # noqa: BLE001
            pass
    return 0
