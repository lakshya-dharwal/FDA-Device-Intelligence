"""
Tests for the SQLite telemetry layer, using an isolated temp DB per test
(the temp_db fixture in conftest swaps telemetry.settings.db_path).
"""

from __future__ import annotations

from src.backend import telemetry

SAMPLE_RESULT = {
    "answer": "Sample answer about infusion pumps.",
    "tools_called": ["search_device_recalls"],
    "input_tokens": 500,
    "output_tokens": 200,
    "cost_usd": 0.0045,
    "latency_ms": 2340.5,
}


def test_init_creates_empty_table(temp_db):
    assert telemetry.get_all_queries() == []


def test_log_and_read_roundtrip(temp_db):
    telemetry.log_query("What recalls for infusion pumps?", SAMPLE_RESULT)
    rows = telemetry.get_all_queries()
    assert len(rows) == 1
    row = rows[0]
    assert row["query"] == "What recalls for infusion pumps?"
    assert row["answer"] == SAMPLE_RESULT["answer"]
    # tools_called must come back as a deserialised list, not a JSON string.
    assert row["tools_called"] == ["search_device_recalls"]
    assert row["cost_usd"] == 0.0045


def test_newest_first_ordering(temp_db):
    telemetry.log_query("first query", SAMPLE_RESULT)
    telemetry.log_query("second query", SAMPLE_RESULT)
    rows = telemetry.get_all_queries()
    assert rows[0]["query"] == "second query"
    assert rows[1]["query"] == "first query"


def test_metrics_empty_db(temp_db):
    metrics = telemetry.get_metrics()
    assert metrics["total_queries"] == 0
    assert metrics["total_cost_usd"] == 0
    assert metrics["avg_latency_ms"] == 0


def test_metrics_aggregate(temp_db):
    telemetry.log_query("q1", {**SAMPLE_RESULT, "cost_usd": 0.01, "latency_ms": 1000,
                               "input_tokens": 100, "output_tokens": 100})
    telemetry.log_query("q2", {**SAMPLE_RESULT, "cost_usd": 0.03, "latency_ms": 3000,
                               "input_tokens": 300, "output_tokens": 300})
    metrics = telemetry.get_metrics()
    assert metrics["total_queries"] == 2
    assert abs(metrics["total_cost_usd"] - 0.04) < 1e-9
    assert metrics["avg_latency_ms"] == 2000
    assert metrics["avg_tokens"] == 400  # (200 + 600) / 2


def test_log_query_with_missing_fields(temp_db):
    # A sparse result dict should still log without raising.
    telemetry.log_query("sparse", {"answer": "hi"})
    rows = telemetry.get_all_queries()
    assert rows[0]["input_tokens"] == 0
    assert rows[0]["tools_called"] == []
