"""
FastAPI backend — exposes the Claude FDA agentic loop via HTTP endpoints.
The Streamlit frontend calls these endpoints; they can also be used directly via curl.
"""

import sys
import os

# Ensure the project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.backend.claude_client import run_fda_query
from src.backend.telemetry import init_db, log_query, get_all_queries, get_metrics

app = FastAPI(
    title="FDA Device Intelligence API",
    description="Agentic AI layer for querying FDA medical device safety data via Claude.",
    version="1.0.0",
)

# Allow requests from the Streamlit frontend (any origin in V1)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup_event():
    """Initialise SQLite telemetry DB when the server starts."""
    init_db()


# ── Request / response models ─────────────────────────────────────────────────

class QueryRequest(BaseModel):
    query: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health_check():
    """Simple liveness probe."""
    return {"status": "ok"}


@app.post("/query")
def query_endpoint(req: QueryRequest):
    """
    Main endpoint: accepts a natural-language question, runs the Claude
    agentic loop with FDA tools, logs the result, and returns it.
    """
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    result = run_fda_query(req.query)
    log_query(req.query, result)
    return result


@app.get("/metrics")
def metrics_endpoint():
    """Aggregate telemetry stats — total queries, cost, latency, tokens."""
    return get_metrics()


@app.get("/history")
def history_endpoint():
    """Full query history, newest first."""
    return get_all_queries()
