"""Faza 3 OpenAI: function calling i dispatch Code/Agent."""

from __future__ import annotations

import json
from types import SimpleNamespace

from caelo_core.agent.runner import AgentRunner
from caelo_core.providers.openai import tools as openai_tools
from caelo_core.providers.openai.tools import OpenAIAgentTools, build_openai_agent_input


class FakeStreamResponse:
    status_code = 200

    def __init__(self, events):
        self.events = events

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def close(self):
        return None

    def raise_for_status(self):
        return None

    def iter_lines(self, decode_unicode=False):
        del decode_unicode
        for event in self.events:
            yield ("data: " + json.dumps(event, ensure_ascii=False)).encode("utf-8")
        yield b"data: [DONE]"


TOOLS = [{"type": "function", "function": {
    "name": "write_file", "description": "Write a file",
    "parameters": {"type": "object", "properties": {
        "path": {"type": "string"}, "content": {"type": "string"},
    }, "required": ["path", "content"]},
}}]


def test_openai_agent_input_replays_raw_reasoning_calls_and_tool_outputs() -> None:
    raw_output = [
        {"type": "reasoning", "id": "rs_1", "encrypted_content": "opaque"},
        {"type": "function_call", "call_id": "call_1", "name": "write_file",
         "arguments": '{"path":"a.txt","content":"A"}'},
    ]
    items = build_openai_agent_input([
        {"role": "system", "content": "Be careful"},
        {"role": "user", "content": "Create a file"},
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call_1", "type": "function", "function": {
                "name": "write_file", "arguments": '{"path":"a.txt","content":"A"}',
            },
        }], "provider_data": {"openai": {"output": raw_output}}},
        {"role": "tool", "tool_call_id": "call_1", "content": "Wrote a.txt"},
    ])
    assert items[2:4] == raw_output
    assert items[4] == {
        "type": "function_call_output", "call_id": "call_1", "output": "Wrote a.txt",
    }


def test_openai_agent_stream_preserves_parallel_call_ids_and_private_payload(monkeypatch) -> None:
    output = [
        {"type": "reasoning", "id": "rs_2", "encrypted_content": "cipher"},
        {"type": "function_call", "call_id": "native-a", "name": "write_file",
         "arguments": '{"path":"żółw.txt","content":"gęślą"}'},
        {"type": "function_call", "call_id": "native-b", "name": "write_file",
         "arguments": '{"path":"b.txt","content":"B"}'},
    ]
    response = FakeStreamResponse([
        {"type": "response.completed", "response": {
            "usage": {"input_tokens": 11, "output_tokens": 5}, "output": output,
        }},
    ])
    captured = {}

    def fake_post(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return response

    monkeypatch.setattr(openai_tools.requests, "post", fake_post)
    result = OpenAIAgentTools(lambda: "sk-agent").stream_chat_with_tools(
        "ignored", "ignored", [{"role": "user", "content": "create"}],
        "gpt-5.6-sol", 0.9, TOOLS, reasoning_effort="high",
    )

    assert [call["id"] for call in result["tool_calls"]] == ["native-a", "native-b"]
    assert json.loads(result["tool_calls"][0]["function"]["arguments"])["path"] == "żółw.txt"
    assert result["provider_data"]["openai"]["output"] == output
    assert result["usage"] == {
        "input_tokens": 11, "output_tokens": 5, "cost_usd": 0.000144,
    }
    assert captured["url"] == "https://api.openai.com/v1/responses"
    assert captured["headers"]["Authorization"] == "Bearer sk-agent"
    payload = captured["json"]
    assert payload["store"] is False
    assert "temperature" not in payload
    assert payload["reasoning"] == {"effort": "high"}
    assert payload["include"] == ["reasoning.encrypted_content"]
    assert payload["tools"][0]["name"] == "write_file"
    assert "function" not in payload["tools"][0]


def test_agent_runner_dispatches_openai_without_falling_back_to_xai() -> None:
    calls = []

    class Agent:
        def stream_chat_with_tools(self, *args, **kwargs):
            calls.append((args, kwargs))
            return {"role": "assistant", "content": "ok"}

    provider = SimpleNamespace(agent=Agent())
    backend = SimpleNamespace(
        get_openai_api_key=lambda: "sk-runner",
        get_api_key=lambda: "xai-must-not-be-used",
        get_provider=lambda provider_id: provider if provider_id == "openai" else None,
    )
    runner = AgentRunner(
        backend, emit=lambda _event: None, request_approval=lambda *_args: "reject",
        stop=lambda: False,
    )
    runner._provider = "openai"
    assert runner._credential() == "sk-runner"
    result = runner._llm_dispatch(
        "sk-runner", "ignored", [{"role": "user", "content": "hello"}],
        "gpt-5.6-sol", 0.2, TOOLS,
    )
    assert result["content"] == "ok"
    assert len(calls) == 1
