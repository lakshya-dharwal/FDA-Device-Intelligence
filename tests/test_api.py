"""
Endpoint tests for the FastAPI app using Starlette's TestClient.

run_fda_query is patched so /query never hits the real Anthropic API, and the
telemetry layer is redirected to a temp DB via the temp_db fixture.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.backend import main
from src.backend.claude_client import ClaudeClientError

FAKE_RESULT = {
    "answer": "Two Class I recalls found for infusion pumps.",
    "tools_called": ["search_device_recalls"],
    "input_tokens": 800,
    "output_tokens": 250,
    "cost_usd": 0.006,
    "latency_ms": 3120.0,
}


@pytest.fixture
def client(temp_db, monkeypatch):
    """TestClient with telemetry on a temp DB and run_fda_query stubbed."""
    monkeypatch.setattr(main, "run_fda_query", lambda q: dict(FAKE_RESULT))
    # The app's lifespan calls init_db(); temp_db already created the schema.
    with TestClient(main.app) as c:
        yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_query_success(client):
    resp = client.post("/query", json={"query": "Class I recalls for infusion pumps"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == FAKE_RESULT["answer"]
    assert body["tools_called"] == ["search_device_recalls"]


def test_query_logs_telemetry(client):
    client.post("/query", json={"query": "Class I recalls for infusion pumps"})
    hist = client.get("/history").json()
    assert len(hist) == 1
    assert hist[0]["query"] == "Class I recalls for infusion pumps"


def test_query_too_short_is_422(client):
    resp = client.post("/query", json={"query": "hi"})
    assert resp.status_code == 422  # fails Pydantic min_length


def test_query_too_long_is_422(client):
    resp = client.post("/query", json={"query": "x" * 501})
    assert resp.status_code == 422  # fails Pydantic max_length


def test_query_whitespace_only_is_400(client):
    resp = client.post("/query", json={"query": "   "})
    assert resp.status_code == 400  # passes length, empty after strip


def test_query_client_error_becomes_502(temp_db, monkeypatch):
    """A ClaudeClientError (billing/auth) should surface as HTTP 502."""
    def _raise(q):
        raise ClaudeClientError("Anthropic API error (400): credit balance too low")
    monkeypatch.setattr(main, "run_fda_query", _raise)
    with TestClient(main.app) as c:
        resp = c.post("/query", json={"query": "valid length query"})
    assert resp.status_code == 502
    assert "credit balance" in resp.json()["detail"]


def test_metrics_endpoint(client):
    client.post("/query", json={"query": "Class I recalls for infusion pumps"})
    metrics = client.get("/metrics").json()
    assert metrics["total_queries"] == 1
    assert metrics["total_cost_usd"] == pytest.approx(0.006)


def test_history_empty(client):
    assert client.get("/history").json() == []
