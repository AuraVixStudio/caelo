"""Self-check serwera ACP (M19-B2) — bez sieci xAI (mock LLM), bez I/O Backendu
(stub backend). Steruje `AcpServer._dispatch` wprost (mock klient ACP), przechwytując
`_send`. Sprawdza: initialize (echo protokołu, tolerancja), nieznana metoda → error,
session/new → sessionId, session/prompt → agent_message_chunk + result(end_turn),
nieznana sesja → error, oraz tool → session/request_permission: 'allow' wykonuje narzędzie
+ tool_call/tool_call_update, 'reject' blokuje. Kod wyjścia 0 = wszystkie asercje OK.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from caelo_core.acp.server import AcpServer  # noqa: E402
from caelo_core.agent import llm as LLM  # noqa: E402
from caelo_core.tools.headless_check import StubBackend, _mock_text, _mock_one_tool  # noqa: E402

checks: list[tuple[str, bool]] = []


def check(name: str, passed: bool) -> None:
    checks.append((name, bool(passed)))


class Harness:
    """Mock klient ACP: wysyła wiadomości przez `_dispatch`, przechwytuje `_send`."""

    def __init__(self, backend) -> None:
        self.server = AcpServer(backend)
        self.sent: list = []
        self.cv = threading.Condition()
        self.server._send = self._capture  # type: ignore[assignment]

    def _capture(self, obj: dict) -> None:
        with self.cv:
            self.sent.append(obj)
            self.cv.notify_all()

    def send(self, msg: dict) -> None:
        self.server._dispatch(msg)

    def wait(self, pred, timeout: float = 5.0) -> bool:
        with self.cv:
            return self.cv.wait_for(lambda: pred(self.sent), timeout=timeout)

    def result_of(self, rid):
        return next((m for m in self.sent if m.get("id") == rid and "result" in m), None)

    def error_of(self, rid):
        return next((m for m in self.sent if m.get("id") == rid and "error" in m), None)

    def updates(self):
        return [m for m in self.sent if m.get("method") == "session/update"]

    def update_kinds(self):
        return [m["params"]["update"]["sessionUpdate"] for m in self.updates()]


def _patch_llm(fn):
    orig = LLM.stream_chat_with_tools
    LLM.stream_chat_with_tools = fn  # AgentRunner importuje leniwie → łapie podmianę
    return orig


def test_handshake() -> None:
    h = Harness(StubBackend())
    h.send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "weird", "clientCapabilities": {}}})
    res = h.result_of(1)
    check("initialize returns result", res is not None)
    check("initialize echoes protocolVersion (tolerant)",
          bool(res) and res["result"]["protocolVersion"] == "weird")
    check("initialize advertises agentCapabilities",
          bool(res) and "agentCapabilities" in res["result"])
    h.send({"jsonrpc": "2.0", "id": 2, "method": "nope/method", "params": {}})
    check("unknown method -> error", h.error_of(2) is not None)


def test_text_prompt() -> None:
    orig = _patch_llm(_mock_text("Hello world"))
    try:
        with tempfile.TemporaryDirectory() as d:
            h = Harness(StubBackend())
            h.send({"jsonrpc": "2.0", "id": 1, "method": "session/new", "params": {"cwd": d}})
            res = h.result_of(1)
            sid = res and res["result"].get("sessionId")
            check("session/new returns sessionId", bool(sid))

            h.send({"jsonrpc": "2.0", "id": 2, "method": "session/prompt",
                    "params": {"sessionId": sid, "prompt": [{"type": "text", "text": "hi"}]}})
            got = h.wait(lambda s: any(m.get("id") == 2 and "result" in m for m in s))
            check("session/prompt returns result", got)
            texts = "".join(u["params"]["update"]["content"]["text"] for u in h.updates()
                            if u["params"]["update"]["sessionUpdate"] == "agent_message_chunk")
            check("agent_message_chunk streams full text", texts == "Hello world")
            res2 = h.result_of(2)
            check("result has stopReason end_turn",
                  bool(res2) and res2["result"]["stopReason"] == "end_turn")

            h.send({"jsonrpc": "2.0", "id": 3, "method": "session/prompt",
                    "params": {"sessionId": "nope", "prompt": []}})
            check("unknown session -> error", h.error_of(3) is not None)
    finally:
        LLM.stream_chat_with_tools = orig


def _run_tool_with_decision(option_id: str, d: str):
    """Uruchom turę z jednym write_file i odpowiedz na request_permission `option_id`.
    Zwraca (harness, sid)."""
    h = Harness(StubBackend())
    h.send({"jsonrpc": "2.0", "id": 1, "method": "session/new", "params": {"cwd": d}})
    sid = h.result_of(1)["result"]["sessionId"]
    h.send({"jsonrpc": "2.0", "id": 2, "method": "session/prompt",
            "params": {"sessionId": sid, "prompt": [{"type": "text", "text": "write"}]}})
    h.wait(lambda s: any(m.get("method") == "session/request_permission" for m in s))
    req = next(m for m in h.sent if m.get("method") == "session/request_permission")
    h.send({"jsonrpc": "2.0", "id": req["id"],
            "result": {"outcome": {"outcome": "selected", "optionId": option_id}}})
    h.wait(lambda s: any(m.get("id") == 2 and "result" in m for m in s))
    return h, req


def test_tool_permission() -> None:
    # allow → narzędzie wykonane
    orig = _patch_llm(_mock_one_tool("write_file", {"path": "a.txt", "content": "hi"}))
    try:
        with tempfile.TemporaryDirectory() as d:
            h, req = _run_tool_with_decision("allow", d)
            check("tool triggers session/request_permission with options",
                  bool(req["params"].get("options")))
            check("approved tool writes file",
                  (Path(d) / "a.txt").read_text(encoding="utf-8") == "hi")
            kinds = h.update_kinds()
            check("tool_call + tool_call_update streamed",
                  "tool_call" in kinds and "tool_call_update" in kinds)
    finally:
        LLM.stream_chat_with_tools = orig

    # reject → narzędzie zablokowane
    orig = _patch_llm(_mock_one_tool("write_file", {"path": "b.txt", "content": "hi"}))
    try:
        with tempfile.TemporaryDirectory() as d:
            h, _ = _run_tool_with_decision("reject", d)
            check("rejected tool does not write file", not (Path(d) / "b.txt").exists())
            res = h.result_of(2)
            check("rejected turn still returns result", bool(res))
    finally:
        LLM.stream_chat_with_tools = orig


def main() -> int:
    test_handshake()
    test_text_prompt()
    test_tool_permission()
    ok = True
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print("RESULT:", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
