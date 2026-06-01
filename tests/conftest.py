"""
Shared pytest fixtures and lightweight fakes.

These fakes stand in for external services (OpenFDA HTTP, the Anthropic SDK)
so the entire suite runs offline, deterministically, and for free.
"""

from __future__ import annotations

import types

import pytest

from src.backend import telemetry


# ── Telemetry: point the DB at a throwaway temp file per test ─────────────────

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Swap telemetry's settings for one pointing at an isolated temp DB."""
    db_file = tmp_path / "test_telemetry.db"
    fake_settings = types.SimpleNamespace(db_path=str(db_file))
    monkeypatch.setattr(telemetry, "settings", fake_settings)
    telemetry.init_db()
    return str(db_file)


# ── OpenFDA: a fake requests.Response ─────────────────────────────────────────

class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, json_data=None, status_code=200, raise_exc=None):
        self._json = json_data if json_data is not None else {}
        self.status_code = status_code
        self._raise_exc = raise_exc

    def json(self):
        if isinstance(self._json, Exception):
            raise self._json
        return self._json

    def raise_for_status(self):
        if self._raise_exc is not None:
            raise self._raise_exc


# ── Anthropic: fake response/blocks/client ────────────────────────────────────

class FakeTextBlock:
    """A Claude content block carrying text."""

    type = "text"

    def __init__(self, text):
        self.text = text


class FakeToolUseBlock:
    """A Claude content block requesting a tool call."""

    type = "tool_use"
    text = ""  # so _extract_text safely skips it

    def __init__(self, name, tool_input, block_id="tool_1"):
        self.name = name
        self.input = tool_input
        self.id = block_id


class FakeUsage:
    def __init__(self, input_tokens, output_tokens):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class FakeMessage:
    """A Claude response: content blocks, stop_reason, and token usage."""

    def __init__(self, content, stop_reason, input_tokens=100, output_tokens=50):
        self.content = content
        self.stop_reason = stop_reason
        self.usage = FakeUsage(input_tokens, output_tokens)


class FakeMessages:
    """Implements .create(), returning queued responses in order."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.call_count = 0

    def create(self, **kwargs):
        self.call_count += 1
        if isinstance(self._responses, Exception):
            raise self._responses
        # Return the next queued response; repeat the last if we run out.
        idx = min(self.call_count - 1, len(self._responses) - 1)
        resp = self._responses[idx]
        if isinstance(resp, Exception):
            raise resp
        return resp


class FakeAnthropicClient:
    """Drop-in for anthropic.Anthropic with a scripted .messages.create()."""

    def __init__(self, responses):
        self.messages = FakeMessages(responses)


@pytest.fixture
def make_client():
    """Factory: build a FakeAnthropicClient from a list of FakeMessage objects."""
    def _make(responses):
        return FakeAnthropicClient(responses)
    return _make
