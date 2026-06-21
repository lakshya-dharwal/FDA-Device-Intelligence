from fastapi.testclient import TestClient

import src.backend.main as main
from src.backend.telemetry import get_metrics, log_query


def test_health_endpoint(temp_db, monkeypatch):
    monkeypatch.setattr(
        main,
        "run_fda_query",
        lambda query: {
            "answer": "ok",
            "tools_called": [],
            "input_tokens": 1,
            "output_tokens": 1,
            "cost_usd": 0.0001,
            "latency_ms": 1.0,
        },
    )
    with TestClient(main.app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_metrics_and_history_are_empty_by_default(temp_db):
    with TestClient(main.app) as client:
        metrics_response = client.get("/metrics")
        history_response = client.get("/history")

    assert metrics_response.status_code == 200
    assert metrics_response.json()["total_queries"] == 0
    assert history_response.status_code == 200
    assert history_response.json() == []


def test_metrics_and_history_reflect_logged_queries(temp_db):
    log_query(
        "first query",
        {
            "answer": "first answer",
            "tools_called": ["search_device_recalls"],
            "input_tokens": 100,
            "output_tokens": 40,
            "cost_usd": 0.0123,
            "latency_ms": 210.5,
        },
    )

    with TestClient(main.app) as client:
        metrics_response = client.get("/metrics")
        history_response = client.get("/history")

    assert metrics_response.status_code == 200
    assert metrics_response.json()["total_queries"] == 1

    history = history_response.json()
    assert history_response.status_code == 200
    assert len(history) == 1
    assert history[0]["query"] == "first query"

    metrics = get_metrics()
    assert metrics["total_queries"] == 1
