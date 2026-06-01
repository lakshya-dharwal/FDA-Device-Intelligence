"""
FastAPI backend — exposes the Claude FDA agentic loop via HTTP endpoints.

The Streamlit frontend calls these endpoints; they can also be exercised
directly via curl. Interactive API docs are available at /docs.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.backend.claude_client import ClaudeClientError, run_fda_query
from src.backend.telemetry import get_all_queries, get_metrics, init_db, log_query
from src.logging_config import get_logger

logger = get_logger(__name__)

# Query length guard rails, applied by the Pydantic model below.
MIN_QUERY_LEN = 3
MAX_QUERY_LEN = 500


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise the telemetry DB on startup (replaces deprecated on_event)."""
    init_db()
    logger.info("FDA Device Intelligence API started")
    yield
    logger.info("FDA Device Intelligence API shutting down")


app = FastAPI(
    title="FDA Device Intelligence API",
    description="Agentic AI layer for querying FDA medical device safety data via Claude.",
    version="1.0.0",
    lifespan=lifespan,
)

# Allow requests from the Streamlit frontend (any origin in V1).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / response models ─────────────────────────────────────────────────

class QueryRequest(BaseModel):
    """Body for POST /query. Length bounds are enforced by Pydantic."""

    query: str = Field(..., min_length=MIN_QUERY_LEN, max_length=MAX_QUERY_LEN)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health", summary="Liveness probe")
def health_check():
    """Return ok if the service is up. Used by load balancers and smoke tests."""
    return {"status": "ok"}


@app.post("/query", summary="Run an FDA intelligence query")
def query_endpoint(req: QueryRequest):
    """
    Accept a natural-language question, run the Claude agentic loop with the
    FDA tools, persist telemetry, and return the answer plus usage metrics.
    """
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    logger.info("Received query: %r", query)
    try:
        result = run_fda_query(query)
    except ClaudeClientError as exc:
        # Config/billing/API failures → 502 with a useful message, not a bare 500.
        logger.error("Query failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    log_query(query, result)
    return result


@app.get("/metrics", summary="Aggregate telemetry")
def metrics_endpoint():
    """Aggregate stats across all queries — count, total cost, avg latency, avg tokens."""
    return get_metrics()


@app.get("/history", summary="Full query history")
def history_endpoint():
    """Return the full query log, newest first."""
    return get_all_queries()
