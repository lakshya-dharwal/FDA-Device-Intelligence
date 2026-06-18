"""
Tests for the Claude agentic loop, using a fully faked Anthropic client
(FakeAnthropicClient in conftest) so no real API calls are made.
"""

from __future__ import annotations

import anthropic
import pytest

from src.backend import claude_client
from src.backend.claude_client import ClaudeClientError, run_fda_query
from tests.conftest import FakeMessage, FakeTextBlock, FakeToolUseBlock


def test_simple_answer_no_tools(make_client):
    """A response with stop_reason != tool_use returns the text directly."""
    client = make_client([
        FakeMessage([FakeTextBlock("Pacemakers are Class III devices.")], "end_turn",
                    input_tokens=120, output_tokens=30),
    ])
    result = run_fda_query("How is a pacemaker classified?", client=client)
    assert result["answer"] == "Pacemakers are Class III devices."
    assert result["tools_called"] == []
    assert result["input_tokens"] == 120
    assert result["output_tokens"] == 30


def test_cost_calculation(make_client):
    """Cost should follow the configured per-MTok pricing (3 / 15)."""
    client = make_client([
        FakeMessage([FakeTextBlock("done")], "end_turn",
                    input_tokens=1_000_000, output_tokens=1_000_000),
    ])
    result = run_fda_query("test", client=client)
    # 1M input * $3 + 1M output * $15 = $18
    assert result["cost_usd"] == pytest.approx(18.0)


def test_tool_use_loop_executes_tool(make_client, monkeypatch):
    """When Claude requests a tool, we run it and feed the result back."""
    # Stub the actual FDA function so no network is touched.
    monkeypatch.setitem(claude_client.TOOL_MAP, "search_device_recalls",
                        lambda **kw: "FAKE RECALL DATA")

    first = FakeMessage(
        [FakeToolUseBlock("search_device_recalls", {"search_term": "pump"})],
        "tool_use", input_tokens=200, output_tokens=80,
    )
    second = FakeMessage([FakeTextBlock("Here are the recalls.")], "end_turn",
                         input_tokens=150, output_tokens=40)
    client = make_client([first, second])

    result = run_fda_query("recalls for pump", client=client)
    assert result["answer"] == "Here are the recalls."
    assert result["tools_called"] == ["search_device_recalls"]
    # Tokens accumulate across both API calls.
    assert result["input_tokens"] == 350
    assert result["output_tokens"] == 120


def test_unknown_tool_is_handled(make_client):
    """An unknown tool name produces an error result, not a crash."""
    first = FakeMessage([FakeToolUseBlock("does_not_exist", {})], "tool_use")
    second = FakeMessage([FakeTextBlock("recovered")], "end_turn")
    client = make_client([first, second])
    result = run_fda_query("weird", client=client)
    assert result["answer"] == "recovered"
    assert result["tools_called"] == ["does_not_exist"]


def test_failing_tool_does_not_kill_loop(make_client, monkeypatch):
    """A tool that raises should be caught and reported back to Claude."""
    def _boom(**kw):
        raise RuntimeError("kaboom")
    monkeypatch.setitem(claude_client.TOOL_MAP, "search_device_recalls", _boom)

    first = FakeMessage(
        [FakeToolUseBlock("search_device_recalls", {"search_term": "x"})], "tool_use")
    second = FakeMessage([FakeTextBlock("handled")], "end_turn")
    client = make_client([first, second])
    result = run_fda_query("test", client=client)
    assert result["answer"] == "handled"


def test_max_iterations_guard(make_client, monkeypatch):
    """A client that always asks for tools must trip the iteration cap."""
    # settings is a frozen dataclass, so swap the whole object for a fake.
    import types
    fake = types.SimpleNamespace(
        max_agent_iterations=3,
        claude_model="claude-sonnet-4-5",
        max_tokens=4096,
        input_cost_per_mtok=3.0,
        output_cost_per_mtok=15.0,
    )
    monkeypatch.setattr(claude_client, "settings", fake)
    monkeypatch.setitem(claude_client.TOOL_MAP, "search_device_recalls", lambda **kw: "data")

    forever = FakeMessage(
        [FakeToolUseBlock("search_device_recalls", {"search_term": "x"})], "tool_use")
    client = make_client([forever])  # FakeMessages repeats the last response

    with pytest.raises(ClaudeClientError, match="maximum"):
        run_fda_query("infinite", client=client)


def test_api_status_error_becomes_client_error(make_client):
    """An Anthropic APIStatusError (e.g. billing) maps to ClaudeClientError."""

    class FakeStatusError(anthropic.APIStatusError):
        def __init__(self):
            self.status_code = 400
            self.message = "credit balance too low"

    client = make_client([FakeStatusError()])
    with pytest.raises(ClaudeClientError, match="400"):
        run_fda_query("test", client=client)


def test_missing_api_key_raises(monkeypatch):
    """get_client() must fail clearly when no API key is configured."""
    # settings is frozen, so swap it for a fake reporting no key.
    import types
    fake = types.SimpleNamespace(has_anthropic_key=False)
    monkeypatch.setattr(claude_client, "settings", fake)
    monkeypatch.setattr(claude_client, "_client", None)
    with pytest.raises(ClaudeClientError, match="ANTHROPIC_API_KEY"):
        claude_client.get_client()
