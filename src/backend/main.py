"""
FastAPI backend — exposes the Claude FDA agentic loop via HTTP endpoints.
The Streamlit frontend calls these endpoints; they can also be used directly via curl.
"""

import sys
import os
import logging
import time
from contextlib import asynccontextmanager
from uuid import uuid4

# Ensure the project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from src.backend.api_models import QueryRequest, QueryResponse
from src.backend.claude_client import run_fda_query
from src.backend.security import RequestRateLimiter, extract_client_ip, parse_bearer_token
from src.backend.settings import get_settings
from src.backend.telemetry import (
    get_all_queries,
    get_metrics,
    get_recent_events,
    init_db,
    log_event,
    log_query,
)
from src.backend.exceptions import (
    BackendError,
    InternalQueryError,
    InvalidQueryError,
)

settings = get_settings()
logging.basicConfig(level=getattr(logging, settings.log_level, logging.INFO))
logger = logging.getLogger(__name__)
rate_limiter = RequestRateLimiter()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database-backed services on startup."""
    init_db()
    yield


app = FastAPI(
    title="FDA Device Intelligence API",
    description="Agentic AI layer for querying FDA medical device safety data via Claude.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Client-ID", "X-Request-ID"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    request.state.request_id = request.headers.get("x-request-id", str(uuid4()))
    request.state.client_ip = extract_client_ip(request)
    request.state.user_id = request.headers.get("x-client-id")
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.middleware("http")
async def auth_and_rate_limit_middleware(request: Request, call_next):
    if not hasattr(request.state, "request_id"):
        request.state.request_id = request.headers.get("x-request-id", str(uuid4()))
    if not hasattr(request.state, "client_ip"):
        request.state.client_ip = extract_client_ip(request)
    if not hasattr(request.state, "user_id"):
        request.state.user_id = request.headers.get("x-client-id")

    if request.url.path == "/health":
        return await call_next(request)

    current_settings = get_settings()
    request_id = getattr(request.state, "request_id", None)
    client_ip = getattr(request.state, "client_ip", extract_client_ip(request))

    if current_settings.api_auth_token:
        token = parse_bearer_token(request)
        if token != current_settings.api_auth_token:
            log_event(
                level="WARNING",
                event_type="auth_failed",
                message="Rejected request with invalid API token.",
                request_id=request_id,
                context={"path": request.url.path, "client_ip": client_ip},
            )
            response = JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "code": "unauthorized",
                        "message": "Valid API credentials are required.",
                        "retryable": False,
                        "request_id": request_id,
                    }
                },
            )
            response.headers["X-Request-ID"] = request_id or ""
            return response
        request.state.user_id = request.state.user_id or "api-token"

    limiter_key = request.state.user_id or client_ip
    if not rate_limiter.allow(
        limiter_key,
        limit=current_settings.rate_limit_requests,
        window_seconds=current_settings.rate_limit_window_seconds,
    ):
        log_event(
            level="WARNING",
            event_type="rate_limit_exceeded",
            message="Rejected request due to rate limiting.",
            request_id=request_id,
            context={
                "path": request.url.path,
                "client_ip": client_ip,
                "limiter_key": limiter_key,
            },
        )
        response = JSONResponse(
            status_code=429,
            content={
                "error": {
                    "code": "rate_limited",
                    "message": "Rate limit exceeded. Please retry later.",
                    "retryable": True,
                    "request_id": request_id,
                }
            },
        )
        response.headers["X-Request-ID"] = request_id or ""
        return response

    return await call_next(request)


@app.exception_handler(BackendError)
def backend_error_handler(request: Request, exc: BackendError):
    request_id = getattr(request.state, "request_id", None)
    log_event(
        level="ERROR",
        event_type="backend_error",
        message=exc.message,
        request_id=request_id,
        context={
            "path": request.url.path,
            "error_code": exc.code,
            "retryable": exc.retryable,
            "details": exc.details,
        },
    )
    logger.warning(
        "Backend error during request",
        extra={
            "request_id": request_id,
            "path": request.url.path,
            "error_code": exc.code,
            "retryable": exc.retryable,
            "details": exc.details,
        },
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_response(request_id=request_id),
    )


@app.exception_handler(Exception)
def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", None)
    log_event(
        level="ERROR",
        event_type="unhandled_exception",
        message=str(exc),
        request_id=request_id,
        context={"path": request.url.path},
    )
    logger.error(
        "Unhandled exception during request",
        extra={"request_id": request_id, "path": request.url.path},
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    error = InternalQueryError()
    return JSONResponse(
        status_code=error.status_code,
        content=error.to_response(request_id=request_id),
    )

# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health_check():
    """Simple liveness probe."""
    return {"status": "ok"}


@app.post("/query", response_model=QueryResponse)
def query_endpoint(req: QueryRequest, request: Request):
    """
    Main endpoint: accepts a natural-language question, runs the Claude
    agentic loop with FDA tools, logs the result, and returns it.
    """
    request_id = request.state.request_id
    start_time = time.monotonic()
    client_ip = getattr(request.state, "client_ip", None)
    user_id = getattr(request.state, "user_id", None)

    def failure_result() -> dict:
        latency_ms = round((time.monotonic() - start_time) * 1000, 1)
        return {
            "answer": "",
            "tools_called": [],
            "tool_results": [],
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0.0,
            "latency_ms": latency_ms,
        }

    if not req.query.strip():
        error = InvalidQueryError()
        log_query(
            req.query,
            failure_result(),
            request_id=request_id,
            status="error",
            error_code=error.code,
            error_message=error.message,
            retryable=error.retryable,
            client_ip=client_ip,
            user_id=user_id,
        )
        raise error

    try:
        result = run_fda_query(req.query)
    except BackendError as exc:
        log_query(
            req.query,
            failure_result(),
            request_id=request_id,
            status="error",
            error_code=exc.code,
            error_message=exc.message,
            retryable=exc.retryable,
            client_ip=client_ip,
            user_id=user_id,
        )
        log_event(
            level="ERROR",
            event_type="query_failed",
            message=exc.message,
            request_id=request_id,
            context={"error_code": exc.code, "client_ip": client_ip, "user_id": user_id},
        )
        logger.warning(
            "Query failed",
            extra={
                "request_id": request_id,
                "error_code": exc.code,
                "retryable": exc.retryable,
                "details": exc.details,
            },
        )
        raise exc
    except Exception as exc:
        error = InternalQueryError()
        log_query(
            req.query,
            failure_result(),
            request_id=request_id,
            status="error",
            error_code=error.code,
            error_message=error.message,
            retryable=error.retryable,
            client_ip=client_ip,
            user_id=user_id,
        )
        log_event(
            level="ERROR",
            event_type="query_failed_unexpected",
            message=str(exc),
            request_id=request_id,
            context={"client_ip": client_ip, "user_id": user_id},
        )
        logger.exception(
            "Query failed with unexpected error",
            extra={"request_id": request_id},
        )
        raise exc

    log_query(
        req.query,
        result,
        request_id=request_id,
        client_ip=client_ip,
        user_id=user_id,
    )
    logger.info(
        "Query completed",
        extra={
            "request_id": request_id,
            "latency_ms": result.get("latency_ms"),
            "tools_called": result.get("tools_called", []),
        },
    )
    return result


@app.get("/metrics")
def metrics_endpoint():
    """Aggregate telemetry stats — total queries, cost, latency, tokens."""
    return get_metrics()


@app.get("/history")
def history_endpoint():
    """Full query history, newest first."""
    return get_all_queries()


@app.get("/events")
def events_endpoint():
    """Recent telemetry events, newest first."""
    return get_recent_events()
