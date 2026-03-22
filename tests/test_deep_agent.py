"""Tests for deepagents integration helpers."""

import asyncio

import pytest

from aetos import deep_agent


def test_validate_chat_message_rejects_empty():
    with pytest.raises(deep_agent.DeepAgentInputError):
        deep_agent.validate_chat_message("   ")


def test_extract_energy_state_payload_valid(sample_state):
    payload = deep_agent.extract_energy_state_payload(sample_state.model_dump_json())

    assert payload is not None
    assert payload["ess_soc"] == sample_state.ess_soc


def test_extract_energy_state_payload_rejects_invalid_json():
    message = "```json\n{\"price\": [1], }\n```"

    with pytest.raises(deep_agent.DeepAgentInputError):
        deep_agent.extract_energy_state_payload(message)


def test_build_deep_agent_registers_tools_and_subagents(monkeypatch):
    captured = {}

    monkeypatch.setattr(deep_agent, "build_azure_model", lambda: object())

    def fake_create_deep_agent(**kwargs):
        captured.update(kwargs)
        return "agent"

    monkeypatch.setattr(deep_agent, "create_deep_agent", fake_create_deep_agent)

    result = deep_agent.build_deep_agent()

    assert result == "agent"
    assert {tool.name for tool in captured["tools"]} == {
        "mcp_forecast",
        "mcp_optimize",
        "mcp_policy_check",
        "mcp_dispatch",
        "mcp_kpi",
    }
    assert [subagent["name"] for subagent in captured["subagents"]] == [
        "strategy-specialist",
        "selection-specialist",
    ]


def test_invoke_deep_agent_normalizes_response(monkeypatch):
    class FakeMessage:
        content = [{"type": "text", "text": "final reply"}]

    class FakeAgent:
        async def ainvoke(self, payload):
            return {"messages": [FakeMessage()]}

    monkeypatch.setattr(deep_agent, "get_deep_agent", lambda: FakeAgent())

    reply = asyncio.run(deep_agent.invoke_deep_agent("optimize now"))

    assert reply == "final reply"
