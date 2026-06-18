import copy
from types import SimpleNamespace

import httpx
import pytest
import anthropic

from src.backend import claude_client
from src.backend.exceptions import (
    InternalQueryError,
    ModelProviderError,
    ModelProviderTimeoutError,
)
from src.backend.settings import AppSettings


class FakeTextBlock:
    def __init__(self, text: str):
        self.type = "text"
        self.text = text


class FakeToolUseBlock:
    def __init__(self, tool_id: str, name: str, tool_input: dict):
        self.type = "tool_use"
        self.id = tool_id
        self.name = name
        self.input = tool_input


class FakeResponse:
    def __init__(self, stop_reason: str, content: list, *, input_tokens: int, output_tokens: int):
        self.stop_reason = stop_reason
        self.content = content
        self.usage = SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


class FakeAnthropicClient:
    def __init__(self, create_fn):
        self.messages = SimpleNamespace(create=create_fn)


def make_settings(**overrides):
    base = {
        "environment": "test",
        "log_level": "INFO",
        "database_url": "sqlite:///test.db",
        "anthropic_api_key": "test-key",
        "anthropic_model": "claude-sonnet-4-5",
        "anthropic_max_tokens": 4096,
        "query_timeout_seconds": 45.0,
        "max_tool_iterations": 8,
        "model_input_cost_per_mtok": 3.0,
        "model_output_cost_per_mtok": 15.0,
        "api_auth_token": None,
        "cors_allowed_origins": ["http://localhost:8501"],
        "trusted_hosts": ["testserver", "localhost", "127.0.0.1"],
        "rate_limit_requests": 60,
        "rate_limit_window_seconds": 60,
        "frontend_backend_url": "http://localhost:8000",
        "frontend_request_timeout_seconds": 30,
        "frontend_api_token": None,
    }
    base.update(overrides)
    return AppSettings(**base)


def test_run_fda_query_completes_tool_loop(monkeypatch):
    responses = iter(
        [
            FakeResponse(
                "tool_use",
                [
                    FakeToolUseBlock(
                        "tool-1",
                        "get_device_classifications",
                        {"device_name": "pacemaker"},
                    )
                ],
                input_tokens=120,
                output_tokens=30,
            ),
            FakeResponse(
                "end_turn",
                [FakeTextBlock("Pacemakers are Class III devices.")],
                input_tokens=80,
                output_tokens=20,
            ),
        ]
    )
    captured_calls = []

    def fake_create(**kwargs):
        captured_calls.append(copy.deepcopy(kwargs))
        return next(responses)

    monkeypatch.setattr(claude_client, "get_settings", lambda: make_settings())
    monkeypatch.setattr(
        claude_client,
        "get_anthropic_client",
        lambda: FakeAnthropicClient(fake_create),
    )
    monkeypatch.setitem(
        claude_client.TOOL_MAP,
        "get_device_classifications",
        lambda device_name: {
            "tool": "get_device_classifications",
            "query": device_name,
            "results": [{"device_name": "Pacemaker", "device_class": "3"}],
            "result_count": 1,
            "normalized_terms": ["pacemaker"],
            "filters": {},
            "search_fields": ["device_name"],
        },
    )

    result = claude_client.run_fda_query("How is a pacemaker classified by the FDA?")

    assert result["tools_called"] == ["get_device_classifications"]
    assert result["tool_results"][0]["tool_name"] == "get_device_classifications"
    assert result["tool_results"][0]["tool_input"] == {"device_name": "pacemaker"}
    assert result["tool_results"][0]["tool_output"]["results"][0]["device_class"] == "3"
    assert result["input_tokens"] == 200
    assert result["output_tokens"] == 50
    assert "Class III" in result["answer"]
    assert '"device_class": "3"' in captured_calls[1]["messages"][-1]["content"][0]["content"]


def test_run_fda_query_maps_provider_timeout(monkeypatch):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")

    def fake_create(**kwargs):
        raise anthropic.APITimeoutError(request=request)

    monkeypatch.setattr(claude_client, "get_settings", lambda: make_settings())
    monkeypatch.setattr(
        claude_client,
        "get_anthropic_client",
        lambda: FakeAnthropicClient(fake_create),
    )

    with pytest.raises(ModelProviderTimeoutError):
        claude_client.run_fda_query("timeout please")


def test_run_fda_query_maps_rate_limit_errors(monkeypatch):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(429, request=request)

    def fake_create(**kwargs):
        raise anthropic.RateLimitError(
            "rate limited",
            response=response,
            body=None,
        )

    monkeypatch.setattr(claude_client, "get_settings", lambda: make_settings())
    monkeypatch.setattr(
        claude_client,
        "get_anthropic_client",
        lambda: FakeAnthropicClient(fake_create),
    )

    with pytest.raises(ModelProviderError) as exc_info:
        claude_client.run_fda_query("rate limit please")

    assert exc_info.value.code == "model_provider_rate_limited"
    assert exc_info.value.retryable is True


def test_run_fda_query_fails_when_tool_loop_exhausted(monkeypatch):
    def fake_create(**kwargs):
        return FakeResponse(
            "tool_use",
            [
                FakeToolUseBlock(
                    "tool-1",
                    "get_device_classifications",
                    {"device_name": "pacemaker"},
                )
            ],
            input_tokens=1,
            output_tokens=1,
        )

    monkeypatch.setattr(
        claude_client,
        "get_settings",
        lambda: make_settings(max_tool_iterations=1),
    )
    monkeypatch.setattr(
        claude_client,
        "get_anthropic_client",
        lambda: FakeAnthropicClient(fake_create),
    )
    monkeypatch.setitem(
        claude_client.TOOL_MAP,
        "get_device_classifications",
        lambda device_name: {
            "tool": "get_device_classifications",
            "query": device_name,
            "results": [{"device_name": "Pacemaker", "device_class": "3"}],
            "result_count": 1,
            "normalized_terms": ["pacemaker"],
            "filters": {},
            "search_fields": ["device_name"],
        },
    )

    with pytest.raises(InternalQueryError) as exc_info:
        claude_client.run_fda_query("loop forever")

    assert exc_info.value.code == "tool_loop_exhausted"


def test_calculate_query_cost_uses_settings_pricing():
    result = claude_client.calculate_query_cost(
        make_settings(
            model_input_cost_per_mtok=2.5,
            model_output_cost_per_mtok=20.0,
        ),
        input_tokens=1000,
        output_tokens=500,
    )

    assert result == pytest.approx(0.0125)
