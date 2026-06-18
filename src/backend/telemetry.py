"""
Telemetry module — SQLite-backed logging for every FDA query.

Each call to run_fda_query() is recorded here for the analytics dashboard.
The public API (init_db / log_query / get_all_queries / get_metrics) is the
swap boundary for V2, where SQLite is replaced by Google Firestore without
touching the FastAPI layer.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from src.config import settings
from src.logging_config import get_logger

logger = get_logger(__name__)


def _get_connection() -> sqlite3.Connection:
    """Return a connection with row_factory so rows come back as dict-like rows."""
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the queries table if it doesn't already exist."""
    try:
        conn = _get_connection()
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS queries (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp     TEXT    NOT NULL,
                    query         TEXT    NOT NULL,
                    answer        TEXT    NOT NULL,
                    tools_called  TEXT    NOT NULL,  -- JSON array string
                    input_tokens  INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL,
                    cost_usd      REAL    NOT NULL,
                    latency_ms    REAL    NOT NULL
                )
            """)
        conn.close()
        logger.info("Telemetry DB initialised at %s", settings.db_path)
    except sqlite3.Error:
        logger.exception("Failed to initialise telemetry DB at %s", settings.db_path)
        raise


def log_query(query: str, result: dict) -> None:
    """Insert one telemetry row from the result dict returned by run_fda_query."""
    try:
        conn = _get_connection()
        with conn:
            conn.execute(
                """
                INSERT INTO queries
                    (timestamp, query, answer, tools_called,
                     input_tokens, output_tokens, cost_usd, latency_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    query,
                    result.get("answer", ""),
                    json.dumps(result.get("tools_called", [])),
                    result.get("input_tokens", 0),
                    result.get("output_tokens", 0),
                    result.get("cost_usd", 0.0),
                    result.get("latency_ms", 0.0),
                ),
            )
        conn.close()
    except sqlite3.Error:
        # Telemetry must never take down a successful user query — log and move on.
        logger.exception("Failed to log query telemetry")


def get_all_queries() -> list[dict]:
    """Return all logged queries as a list of dicts, newest first."""
    try:
        conn = _get_connection()
        rows = conn.execute("SELECT * FROM queries ORDER BY id DESC").fetchall()
        conn.close()
    except sqlite3.Error:
        logger.exception("Failed to read query history")
        return []

    result = []
    for row in rows:
        d = dict(row)
        # Deserialise the JSON tools_called column back to a Python list.
        try:
            d["tools_called"] = json.loads(d["tools_called"])
        except (json.JSONDecodeError, TypeError):
            d["tools_called"] = []
        result.append(d)
    return result


def get_metrics() -> dict:
    """Return aggregate statistics across all logged queries."""
    try:
        conn = _get_connection()
        row = conn.execute(
            """
            SELECT
                COUNT(*)                                       AS total_queries,
                COALESCE(SUM(cost_usd), 0)                     AS total_cost_usd,
                COALESCE(AVG(latency_ms), 0)                   AS avg_latency_ms,
                COALESCE(AVG(input_tokens + output_tokens), 0) AS avg_tokens
            FROM queries
            """
        ).fetchone()
        conn.close()
        return dict(row)
    except sqlite3.Error:
        logger.exception("Failed to compute metrics")
        return {
            "total_queries": 0,
            "total_cost_usd": 0,
            "avg_latency_ms": 0,
            "avg_tokens": 0,
        }
