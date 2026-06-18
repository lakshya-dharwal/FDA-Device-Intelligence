from src.backend import settings
from src.backend.telemetry import get_metrics, log_event, log_query
import src.backend.main as main


def test_health_endpoint(api_client):
    response = api_client("GET", "/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_metrics_and_history_are_empty_by_default(api_client):
    metrics_response = api_client("GET", "/metrics")
    history_response = api_client("GET", "/history")

    assert metrics_response.status_code == 200
    assert metrics_response.json()["total_queries"] == 0
    assert metrics_response.json()["successful_queries"] == 0
    assert metrics_response.json()["failed_queries"] == 0
    assert history_response.status_code == 200
    assert history_response.json() == []


def test_metrics_and_history_reflect_logged_queries(api_client):
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
        request_id="req-1",
    )
    log_query(
        "second query",
        {
            "answer": "",
            "tools_called": [],
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0.0,
            "latency_ms": 80.0,
        },
        request_id="req-2",
        status="error",
        error_code="fda_upstream_timeout",
        error_message="The FDA data source did not respond in time.",
        retryable=True,
    )

    metrics_response = api_client("GET", "/metrics")
    history_response = api_client("GET", "/history")

    assert metrics_response.status_code == 200
    assert metrics_response.json()["total_queries"] == 2
    assert metrics_response.json()["successful_queries"] == 1
    assert metrics_response.json()["failed_queries"] == 1

    history = history_response.json()
    assert history_response.status_code == 200
    assert len(history) == 2
    assert history[0]["query"] == "second query"
    assert history[0]["status"] == "error"
    assert history[0]["error_code"] == "fda_upstream_timeout"
    assert history[0]["retryable"] is True
    assert history[1]["query"] == "first query"

    # Sanity check the direct telemetry path matches the API aggregate.
    metrics = get_metrics()
    assert metrics["total_queries"] == 2


def test_query_endpoint_returns_structured_tool_results(api_client, monkeypatch):
    monkeypatch.setattr(
        main,
        "run_fda_query",
        lambda query: {
            "answer": "Summary answer",
            "tools_called": ["get_device_classifications"],
            "tool_results": [
                {
                    "tool_name": "get_device_classifications",
                    "tool_input": {"device_name": "pacemaker"},
                    "tool_output": {
                        "tool": "get_device_classifications",
                        "query": "pacemaker",
                        "normalized_terms": ["pacemaker"],
                        "filters": {},
                        "search_fields": ["device_name"],
                        "result_count": 1,
                        "results": [
                            {
                                "device_name": "Pacemaker",
                                "device_class": "3",
                            }
                        ],
                    },
                }
            ],
            "input_tokens": 100,
            "output_tokens": 50,
            "cost_usd": 0.001,
            "latency_ms": 123.4,
        },
    )

    response = api_client("POST", "/query", json={"query": "How is a pacemaker classified?"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "Summary answer"
    assert payload["tool_results"][0]["tool_name"] == "get_device_classifications"
    assert payload["tool_results"][0]["tool_output"]["results"][0]["device_class"] == "3"


def test_events_endpoint_returns_logged_events(api_client):
    log_event(
        level="WARNING",
        event_type="rate_limit_exceeded",
        message="Rate limit test event",
        request_id="req-events",
        context={"path": "/query"},
    )

    response = api_client("GET", "/events")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["event_type"] == "rate_limit_exceeded"
    assert payload[0]["request_id"] == "req-events"


def test_metrics_requires_auth_when_token_configured(api_client, monkeypatch):
    monkeypatch.setenv("API_AUTH_TOKEN", "secret-token")
    settings.get_settings.cache_clear()

    response = api_client("GET", "/metrics")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_metrics_returns_429_when_rate_limited(api_client, monkeypatch):
    monkeypatch.setattr(main.rate_limiter, "allow", lambda *args, **kwargs: False)

    response = api_client("GET", "/metrics")

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
