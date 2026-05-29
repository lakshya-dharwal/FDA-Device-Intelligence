"""
Telemetry module — SQLite-backed logging for every FDA query.
Each call to run_fda_query() is recorded here for the analytics dashboard.
"""

import sqlite3
import json
import os
from datetime import datetime

# Database file lives at the project root so it's easy to find
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "telemetry.db")


def _get_connection() -> sqlite3.Connection:
    """Return a connection with row_factory so rows come back as dicts."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the queries table if it doesn't already exist."""
    conn = _get_connection()
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
    conn.commit()
    conn.close()


def log_query(query: str, result: dict) -> None:
    """Insert one telemetry row from the result dict returned by run_fda_query."""
    conn = _get_connection()
    conn.execute(
        """
        INSERT INTO queries
            (timestamp, query, answer, tools_called, input_tokens, output_tokens, cost_usd, latency_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.utcnow().isoformat(),
            query,
            result.get("answer", ""),
            json.dumps(result.get("tools_called", [])),
            result.get("input_tokens", 0),
            result.get("output_tokens", 0),
            result.get("cost_usd", 0.0),
            result.get("latency_ms", 0.0),
        ),
    )
    conn.commit()
    conn.close()


def get_all_queries() -> list[dict]:
    """Return all logged queries as a list of dicts, newest first."""
    conn = _get_connection()
    rows = conn.execute(
        "SELECT * FROM queries ORDER BY id DESC"
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        # Deserialise the JSON tools_called column back to a Python list
        d["tools_called"] = json.loads(d["tools_called"])
        result.append(d)
    return result


def get_metrics() -> dict:
    """Return aggregate statistics across all logged queries."""
    conn = _get_connection()
    row = conn.execute(
        """
        SELECT
            COUNT(*)          AS total_queries,
            COALESCE(SUM(cost_usd), 0)      AS total_cost_usd,
            COALESCE(AVG(latency_ms), 0)    AS avg_latency_ms,
            COALESCE(AVG(input_tokens + output_tokens), 0) AS avg_tokens
        FROM queries
        """
    ).fetchone()
    conn.close()
    return dict(row)
