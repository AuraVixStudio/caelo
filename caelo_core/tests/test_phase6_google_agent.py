"""Contract and safety-equivalence tests for Phase 6 (Gemini Code/Agent)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from caelo_core.agent.checkpoints import CheckpointManager
from caelo_core.agent.permissions import PermissionGate
from caelo_core.agent.session import AgentSession
from caelo_core.agent.workspace import Workspace
from caelo_core.agent.tools import scrubbed_env
from caelo_core.providers.google.tools import (
    GoogleAgentTools,
    build_google_agent_payload,
)


class FakeGoogleClient:
    def __init__(self, chunks):
        self.chunks = chunks
        self.calls = []

    def stream_generate_content(self, model, payload):
        self.calls.append((model, payload))
        yield from self.chunks


TOOLS = [{"type": "function", "function": {
    "name": "write_file", "description": "Write a file",
    "parameters": {"type": "object", "properties": {
        "path": {"type": "string"}, "content": {"type": "string"},
    }, "required": ["path", "content"]},
}}]


def test_google_payload_maps_declarations_parallel_responses_and_signature() -> None:
    messages = [
        {"role": "system", "content": "Be careful."},
        {"role": "user", "content": "Create two files"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "native-a", "type": "function", "function": {
                "name": "write_file", "arguments": '{"path":"a.txt","content":"A"}'
            }},
            {"id": "native-b", "type": "function", "function": {
                "name": "write_file", "arguments": '{"path":"b.txt","content":"B"}'
            }},
        ], "provider_data": {"google": {"content": {"role": "model", "parts": [
            {"functionCall": {"id": "native-a", "name": "write_file",
                              "args": {"path": "a.txt", "content": "A"}},
             "thoughtSignature": "opaque-signature"},
            {"functionCall": {"id": "native-b", "name": "write_file",
                              "args": {"path": "b.txt", "content": "B"}}},
        ]}}}},
        {"role": "tool", "tool_call_id": "native-a", "content": "ok-a"},
        {"role": "tool", "tool_call_id": "native-b", "content": "ok-b"},
    ]
    payload = build_google_agent_payload(
        messages, model="gemini-3.6-flash", tools=TOOLS, reasoning_effort="high")

    assert payload["tools"][0]["functionDeclarations"][0]["name"] == "write_file"
    assert payload["toolConfig"]["functionCallingConfig"] == {
        "mode": "AUTO", "streamFunctionCallArguments": True,
    }
    assert payload["contents"][1]["parts"][0]["thoughtSignature"] == "opaque-signature"
    responses = payload["contents"][2]["parts"]
    assert [part["functionResponse"]["id"] for part in responses] == ["native-a", "native-b"]
    assert [part["functionResponse"]["name"] for part in responses] == ["write_file"] * 2
    assert all(setting["threshold"] == "OFF" for setting in payload["safetySettings"])


def test_google_adapter_preserves_native_id_and_synthesizes_missing_id() -> None:
    client = FakeGoogleClient([{"candidates": [{"content": {"parts": [
        {"functionCall": {"id": "call-native", "name": "write_file",
                          "args": {"path": "żółw.txt", "content": "gęślą"}},
         "thoughtSignature": "signature-1"},
        {"functionCall": {"name": "write_file",
                          "args": {"path": "b.txt", "content": "B"}}},
    ]}}], "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 3}}])
    adapter = GoogleAgentTools(client)  # type: ignore[arg-type]
    result = adapter.stream_chat_with_tools(
        "", "", [{"role": "user", "content": "write"}], "gemini-3.6-flash", 0.2, TOOLS)

    assert [call["id"] for call in result["tool_calls"]] == ["call-native", "google_call_1"]
    assert json.loads(result["tool_calls"][0]["function"]["arguments"])["path"] == "żółw.txt"
    replay = result["provider_data"]["google"]["content"]["parts"]
    assert replay[0]["thoughtSignature"] == "signature-1"
    assert result["usage"] == {"input_tokens": 7, "output_tokens": 3}


def test_google_adapter_assembles_streamed_jsonpath_arguments() -> None:
    client = FakeGoogleClient([
        {"candidates": [{"content": {"parts": [{"functionCall": {
            "id": "p1", "name": "write_file", "partialArgs": [
                {"jsonPath": "$.path", "stringValue": "src/"},
                {"jsonPath": "$.meta[0].name", "stringValue": "Ca"},
            ], "willContinue": True}}]}}]},
        {"candidates": [{"content": {"parts": [{"functionCall": {
            "partialArgs": [
                {"jsonPath": "$.path", "stringValue": "main.py"},
                {"jsonPath": "$.meta[0].name", "stringValue": "elo"},
            ], "willContinue": False}}]}}]},
        {"candidates": [{"content": {"parts": [{"functionCall": {}}]}}],
         "finishReason": "STOP"},
    ])
    result = GoogleAgentTools(client).stream_chat_with_tools(  # type: ignore[arg-type]
        "", "", [{"role": "user", "content": "write"}], "gemini-3.6-flash", 0.2, TOOLS)
    args = json.loads(result["tool_calls"][0]["function"]["arguments"])
    assert args == {"path": "src/main.py", "meta": [{"name": "Caelo"}]}


def _neutral_script():
    calls = 0

    def llm(api_key, base_url, messages, model, temperature, tools, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"role": "assistant", "content": None, "tool_calls": [{
                "id": "write-1", "type": "function", "function": {
                    "name": "write_file",
                    "arguments": '{"path":"created.txt","content":"same safety path"}',
                },
            }]}
        return {"role": "assistant", "content": "done"}

    return llm


def test_xai_and_google_share_approval_checkpoint_and_tool_loop(tmp_path: Path) -> None:
    results = {}
    for provider in ("xai", "google", "openai"):
        root = tmp_path / provider
        root.mkdir()
        approvals = []
        events = []
        checkpoints = CheckpointManager(root, session_id=provider)
        session = AgentSession(
            Workspace(str(root)), PermissionGate(), _neutral_script(), lambda: "key", "base",
            emit=events.append,
            request_approval=lambda call_id, name, detail: approvals.append((call_id, name)) or "accept",
            checkpoints_provider=lambda: checkpoints,
            provider_id_provider=lambda p=provider: p,
        )
        session.run_turn("create", "model")
        results[provider] = {
            "approvals": approvals,
            "content": (root / "created.txt").read_text(encoding="utf-8"),
            "checkpoint_count": len(checkpoints.list()["checkpoints"]),
            "event_types": [event["type"] for event in events],
            "tool_results": [message for message in session.history if message.get("role") == "tool"],
            "tool_names": {tool["function"]["name"] for tool in session._all_tools()},
        }

    for provider in ("xai", "google", "openai"):
        assert results[provider]["approvals"] == [("write-1", "write_file")]
        assert results[provider]["content"] == "same safety path"
        assert results[provider]["checkpoint_count"] == 1
        assert results[provider]["tool_results"][0]["tool_call_id"] == "write-1"
    assert results["xai"]["event_types"] == results["google"]["event_types"]
    assert results["xai"]["event_types"] == results["openai"]["event_types"]
    assert "web_search" in results["xai"]["tool_names"] or "web_search" not in results["google"]["tool_names"]
    assert "web_search" not in results["google"]["tool_names"]


@pytest.mark.parametrize("provider", ["xai", "google", "openai"])
def test_equivalence_loop_guard_and_interrupted_results(tmp_path: Path, provider: str) -> None:
    events = []

    def repeating(api_key, base_url, messages, model, temperature, tools, **kwargs):
        return {"role": "assistant", "content": None, "tool_calls": [{
            "id": "same-call", "type": "function",
            "function": {"name": "read_file", "arguments": '{"path":"missing.txt"}'},
        }]}

    session = AgentSession(
        Workspace(str(tmp_path)), PermissionGate(), repeating, lambda: "", "",
        emit=events.append, request_approval=lambda *args: "reject", max_iters=10,
        provider_id_provider=lambda: provider,
    )
    session.run_turn("repeat", "model")
    assert any(event["type"] == "stopped" for event in events)
    assistant_calls = [message for message in session.history
                       if message.get("role") == "assistant"]
    tool_results = [message for message in session.history if message.get("role") == "tool"]
    assert len(assistant_calls) == len(tool_results) == 4
    assert tool_results[-1]["content"].startswith("loop guard")

    # A stopped parallel batch must produce one synthetic response per pending call.
    session._finalize_interrupted([
        {"id": "parallel-a", "function": {"name": "read_file", "arguments": "{}"}},
        {"id": "parallel-b", "function": {"name": "grep", "arguments": "{}"}},
    ])
    assert [message["tool_call_id"] for message in session.history[-2:]] == [
        "parallel-a", "parallel-b",
    ]


@pytest.mark.parametrize("provider", ["xai", "google", "openai"])
def test_equivalence_command_environment_is_scrubbed(
    monkeypatch: pytest.MonkeyPatch, provider: str,
) -> None:
    # Provider choice cannot widen the subprocess environment: the same executor
    # removes credentials before every run_command invocation.
    monkeypatch.setenv("XAI_API_KEY", "xai-secret")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "google-secret.json")
    monkeypatch.setenv("CAELO_CORE_TOKEN", "session-secret")
    env = scrubbed_env()
    assert "XAI_API_KEY" not in env
    assert "GOOGLE_APPLICATION_CREDENTIALS" not in env
    assert "CAELO_CORE_TOKEN" not in env
    assert provider in {"xai", "google", "openai"}
