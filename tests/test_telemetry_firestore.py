"""
Tests for the Firestore telemetry backend.

We don't run a live Firestore here — instead we verify the public API matches
the SQLite backend and that failures degrade gracefully (log, never raise) when
no Firestore client can be built. A success path is covered with a fake
collection injected via the module's cached _collection.
"""

from __future__ import annotations

from src.backend import telemetry as telemetry_sqlite
from src.backend import telemetry_firestore


def test_public_api_matches_sqlite():
    """Firestore backend must expose the same callable interface as SQLite."""
    for name in ("init_db", "log_query", "get_all_queries", "get_metrics"):
        assert callable(getattr(telemetry_firestore, name))
        assert callable(getattr(telemetry_sqlite, name))
    # init_firestore alias points at the uniform init_db.
    assert telemetry_firestore.init_firestore is telemetry_firestore.init_db


def test_log_query_degrades_gracefully(monkeypatch):
    """If the Firestore client can't be built, log_query must not raise."""
    def _boom():
        raise RuntimeError("no credentials")
    monkeypatch.setattr(telemetry_firestore, "_get_collection", _boom)
    # Should swallow the error internally.
    telemetry_firestore.log_query("q", {"answer": "a"})


def test_get_metrics_degrades_to_zeros(monkeypatch):
    def _boom():
        raise RuntimeError("no credentials")
    monkeypatch.setattr(telemetry_firestore, "_get_collection", _boom)
    metrics = telemetry_firestore.get_metrics()
    assert metrics["total_queries"] == 0
    assert metrics["total_cost_usd"] == 0


def test_get_all_queries_degrades_to_empty(monkeypatch):
    def _boom():
        raise RuntimeError("no credentials")
    monkeypatch.setattr(telemetry_firestore, "_get_collection", _boom)
    assert telemetry_firestore.get_all_queries() == []


class _FakeDoc:
    def __init__(self, data):
        self._data = data

    def to_dict(self):
        return self._data


class _FakeCollection:
    """Minimal fake supporting .add() and .stream() for metric aggregation."""

    def __init__(self):
        self.docs = []

    def add(self, data):
        self.docs.append(_FakeDoc(data))

    def stream(self):
        return list(self.docs)


def test_log_and_metrics_with_fake_collection(monkeypatch):
    fake = _FakeCollection()
    monkeypatch.setattr(telemetry_firestore, "_get_collection", lambda: fake)

    telemetry_firestore.log_query("q1", {
        "answer": "a", "tools_called": ["t"],
        "input_tokens": 100, "output_tokens": 100,
        "cost_usd": 0.01, "latency_ms": 1000,
    })
    telemetry_firestore.log_query("q2", {
        "answer": "b", "tools_called": [],
        "input_tokens": 300, "output_tokens": 300,
        "cost_usd": 0.03, "latency_ms": 3000,
    })

    metrics = telemetry_firestore.get_metrics()
    assert metrics["total_queries"] == 2
    assert abs(metrics["total_cost_usd"] - 0.04) < 1e-9
    assert metrics["avg_latency_ms"] == 2000
    assert metrics["avg_tokens"] == 400
