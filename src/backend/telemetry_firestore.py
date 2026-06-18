"""
Firestore telemetry backend (V2 cloud deployment).

Mirrors the public API of telemetry.py (init_db / log_query / get_all_queries /
get_metrics) so the FastAPI layer is backend-agnostic. SQLite stays the default
for local dev and tests; this module activates when TELEMETRY_BACKEND=firestore
(set on Cloud Run), authenticating via Application Default Credentials.

firebase-admin is imported lazily so importing this module never fails when the
SDK isn't installed, and so a telemetry hiccup can never take down a user query.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.config import settings
from src.logging_config import get_logger

logger = get_logger(__name__)

# Cached collection reference so we build the client only once per process.
_collection = None


def _get_collection():
    """Return (and lazily initialise) the Firestore collection reference."""
    global _collection
    if _collection is not None:
        return _collection

    import firebase_admin
    from firebase_admin import firestore

    # initialize_app() with no args uses Application Default Credentials
    # (the Cloud Run service account), so no key file is needed in production.
    if not firebase_admin._apps:
        firebase_admin.initialize_app()

    db = firestore.client()
    _collection = db.collection(settings.firestore_collection)
    return _collection


def init_db() -> None:
    """Warm the Firestore client and confirm connectivity on startup."""
    try:
        _get_collection()
        logger.info(
            "Firestore telemetry backend ready (collection=%s)",
            settings.firestore_collection,
        )
    except Exception:
        logger.exception("Failed to initialise Firestore client")
        raise


# Alias matching the V2 scope's naming, pointing at the uniform interface name.
init_firestore = init_db


def log_query(query: str, result: dict) -> None:
    """Write one telemetry document. Failures are logged, never raised."""
    try:
        col = _get_collection()
        col.add({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "query": query,
            "answer": result.get("answer", ""),
            # Firestore stores native arrays — no JSON string needed.
            "tools_called": result.get("tools_called", []),
            "input_tokens": result.get("input_tokens", 0),
            "output_tokens": result.get("output_tokens", 0),
            "cost_usd": result.get("cost_usd", 0.0),
            "latency_ms": result.get("latency_ms", 0.0),
        })
    except Exception:
        logger.exception("Failed to log query to Firestore")


def get_all_queries() -> list[dict]:
    """Return all telemetry documents as dicts, newest first."""
    try:
        from firebase_admin import firestore

        col = _get_collection()
        docs = (
            col.order_by("timestamp", direction=firestore.Query.DESCENDING).stream()
        )
        return [doc.to_dict() for doc in docs]
    except Exception:
        logger.exception("Failed to read query history from Firestore")
        return []


def get_metrics() -> dict:
    """
    Aggregate stats across all telemetry documents.

    Firestore has no SQL-style aggregation for averages, so we stream the
    documents and aggregate in Python. This is fine at telemetry scale; if the
    collection grows large, switch to scheduled rollups or count() aggregation.
    """
    empty = {"total_queries": 0, "total_cost_usd": 0, "avg_latency_ms": 0, "avg_tokens": 0}
    try:
        col = _get_collection()
        docs = list(col.stream())
        if not docs:
            return empty

        total = len(docs)
        total_cost = 0.0
        total_latency = 0.0
        total_tokens = 0
        for doc in docs:
            d = doc.to_dict()
            total_cost += d.get("cost_usd", 0.0)
            total_latency += d.get("latency_ms", 0.0)
            total_tokens += d.get("input_tokens", 0) + d.get("output_tokens", 0)

        return {
            "total_queries": total,
            "total_cost_usd": total_cost,
            "avg_latency_ms": total_latency / total,
            "avg_tokens": total_tokens / total,
        }
    except Exception:
        logger.exception("Failed to compute metrics from Firestore")
        return empty
