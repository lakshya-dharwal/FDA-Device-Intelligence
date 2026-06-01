"""
FDA MCP Tools — three functions that query the public OpenFDA API.

Each function is also registered as an MCP tool so this file can run as a
standalone MCP server (called by Claude via the MCP protocol). The plain
functions are imported directly by the backend's agentic loop.
"""

from __future__ import annotations

import requests
from mcp.server.fastmcp import FastMCP

from src.config import settings
from src.logging_config import get_logger

logger = get_logger(__name__)

# Initialise the FastMCP server (name shows up in Claude's tool list).
mcp = FastMCP("fda-device-intelligence")

# OpenFDA caps `limit` at 1000 and requires it to be positive.
_OPENFDA_MAX_LIMIT = 1000


def _clamp_limit(limit: int) -> int:
    """Clamp a requested result limit into OpenFDA's valid 1..1000 range."""
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        return 10
    return max(1, min(limit, _OPENFDA_MAX_LIMIT))


def _escape(term: str) -> str:
    """Escape double quotes so a search term can't break the Lucene query."""
    return (term or "").replace('"', '\\"').strip()


def _query_openfda(endpoint: str, params: dict) -> tuple[list[dict] | None, str | None]:
    """
    Execute a GET against an OpenFDA endpoint.

    Returns a (results, error) tuple: exactly one is non-None. `results` is the
    parsed list under the "results" key (possibly empty); `error` is a
    human-readable message suitable for feeding back to Claude.
    """
    url = f"{settings.openfda_base}{endpoint}"
    try:
        resp = requests.get(url, params=params, timeout=settings.openfda_timeout)
        # OpenFDA returns 404 with a "no matches" body for empty searches.
        if resp.status_code == 404:
            return [], None
        resp.raise_for_status()
        data = resp.json()
        return data.get("results", []), None
    except requests.Timeout:
        logger.warning("OpenFDA request timed out: %s", url)
        return None, f"OpenFDA request timed out after {settings.openfda_timeout}s."
    except requests.ConnectionError:
        logger.warning("OpenFDA connection error: %s", url)
        return None, "Could not connect to the OpenFDA API."
    except requests.HTTPError as exc:
        logger.warning("OpenFDA HTTP error %s: %s", endpoint, exc)
        return None, f"OpenFDA API returned an error: {exc}."
    except ValueError as exc:  # JSON decode failure
        logger.warning("OpenFDA returned invalid JSON for %s: %s", endpoint, exc)
        return None, "OpenFDA returned an unreadable response."
    except Exception as exc:  # pragma: no cover - defensive catch-all
        logger.exception("Unexpected error querying OpenFDA %s", endpoint)
        return None, f"Unexpected error querying OpenFDA: {exc}."


# ── 1. Device Recalls ────────────────────────────────────────────────────────

def search_device_recalls(search_term: str, limit: int = 10) -> str:
    """Query the OpenFDA device recall endpoint and return a formatted summary."""
    term = _escape(search_term)
    logger.info("Searching device recalls for %r (limit=%s)", term, limit)
    params = {
        "search": f'product_description:"{term}" OR reason_for_recall:"{term}"',
        "limit": _clamp_limit(limit),
    }
    results, error = _query_openfda("/device/recall.json", params)
    if error:
        return error
    if not results:
        return f"No recalls found for '{search_term}'."

    lines = [f"Found {len(results)} recall(s) for '{search_term}':\n"]
    for r in results:
        lines.append(
            f"- [{r.get('recall_initiation_date', 'N/A')}] "
            f"{r.get('recalling_firm', 'Unknown firm')} | "
            f"Class {r.get('classification', '?')} | "
            f"{(r.get('product_description') or 'No description')[:120]} | "
            f"Reason: {(r.get('reason_for_recall') or 'N/A')[:120]}"
        )
    return "\n".join(lines)


# ── 2. Adverse Events ────────────────────────────────────────────────────────

def get_adverse_events(device_name: str, limit: int = 10) -> str:
    """Query the OpenFDA device adverse event (MAUDE) endpoint."""
    name = _escape(device_name)
    logger.info("Fetching adverse events for %r (limit=%s)", name, limit)
    params = {
        "search": f'device.brand_name:"{name}"',
        "limit": _clamp_limit(limit),
    }
    results, error = _query_openfda("/device/event.json", params)
    if error:
        return error
    if not results:
        return f"No adverse events found for '{device_name}'."

    lines = [f"Found {len(results)} adverse event report(s) for '{device_name}':\n"]
    for r in results:
        # Each report may carry multiple devices / narratives; read defensively.
        devices = r.get("device") or [{}]
        dev = devices[0] if devices else {}
        mdr_text = r.get("mdr_text") or [{}]
        narrative = (mdr_text[0].get("text") if mdr_text else None) or "No narrative"
        patients = r.get("patient") or []
        outcome = patients[0].get("sequence_number_outcome", "N/A") if patients else "N/A"
        lines.append(
            f"- [{r.get('date_received', 'N/A')}] "
            f"Brand: {dev.get('brand_name', 'N/A')} | "
            f"Event type: {r.get('event_type', 'N/A')} | "
            f"Outcome: {outcome} | "
            f"Narrative: {narrative[:200]}"
        )
    return "\n".join(lines)


# ── 3. Device Classifications ────────────────────────────────────────────────

def get_device_classifications(device_name: str, limit: int = 5) -> str:
    """Query the OpenFDA device classification endpoint."""
    name = _escape(device_name)
    logger.info("Fetching classifications for %r", name)
    params = {
        "search": f'device_name:"{name}"',
        "limit": _clamp_limit(limit),
    }
    results, error = _query_openfda("/device/classification.json", params)
    if error:
        return error
    if not results:
        return f"No classification data found for '{device_name}'."

    lines = [f"Classification data for '{device_name}':\n"]
    for r in results:
        lines.append(
            f"- Device: {r.get('device_name', 'N/A')} | "
            f"Class: {r.get('device_class', '?')} | "
            f"Regulation #: {r.get('regulation_number', 'N/A')} | "
            f"Product code: {r.get('product_code', 'N/A')} | "
            f"Panel: {r.get('medical_specialty_description', 'N/A')}"
        )
    return "\n".join(lines)


# ── MCP tool wrappers ────────────────────────────────────────────────────────
# These decorators register the plain functions above as MCP tools.

@mcp.tool()
def mcp_search_device_recalls(search_term: str, limit: int = 10) -> str:
    """Search FDA device recalls by product description or reason for recall."""
    return search_device_recalls(search_term, limit)


@mcp.tool()
def mcp_get_adverse_events(device_name: str, limit: int = 10) -> str:
    """Retrieve adverse event (MAUDE) reports for a named medical device."""
    return get_adverse_events(device_name, limit)


@mcp.tool()
def mcp_get_device_classifications(device_name: str) -> str:
    """Look up FDA device classification (class I/II/III) for a device name."""
    return get_device_classifications(device_name)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
