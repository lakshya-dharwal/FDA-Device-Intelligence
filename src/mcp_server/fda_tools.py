"""
FDA MCP Tools — three functions that query the public OpenFDA API.
Each function is also registered as an MCP tool so this file can run
as a standalone MCP server (called by Claude via the MCP protocol).
"""

import requests
from mcp.server.fastmcp import FastMCP

# Initialise the FastMCP server (name shows up in Claude's tool list)
mcp = FastMCP("fda-device-intelligence")

OPENFDA_BASE = "https://api.fda.gov"


# ── 1. Device Recalls ────────────────────────────────────────────────────────

def search_device_recalls(search_term: str, limit: int = 10) -> str:
    """Query OpenFDA device recall endpoint and return a formatted summary."""
    url = f"{OPENFDA_BASE}/device/recall.json"
    params = {
        "search": f'product_description:"{search_term}" OR reason_for_recall:"{search_term}"',
        "limit": limit,
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        if not results:
            return f"No recalls found for '{search_term}'."

        lines = [f"Found {len(results)} recall(s) for '{search_term}':\n"]
        for r in results:
            lines.append(
                f"- [{r.get('recall_initiation_date', 'N/A')}] "
                f"{r.get('recalling_firm', 'Unknown firm')} | "
                f"Class {r.get('classification', '?')} | "
                f"{r.get('product_description', 'No description')[:120]} | "
                f"Reason: {r.get('reason_for_recall', 'N/A')[:120]}"
            )
        return "\n".join(lines)
    except requests.HTTPError as e:
        return f"OpenFDA recall API error: {e}"
    except Exception as e:
        return f"Unexpected error querying recalls: {e}"


# ── 2. Adverse Events ────────────────────────────────────────────────────────

def get_adverse_events(device_name: str, limit: int = 10) -> str:
    """Query OpenFDA device adverse event (MAUDE) endpoint."""
    url = f"{OPENFDA_BASE}/device/event.json"
    params = {
        "search": f'device.brand_name:"{device_name}"',
        "limit": limit,
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        if not results:
            return f"No adverse events found for '{device_name}'."

        lines = [f"Found {len(results)} adverse event report(s) for '{device_name}':\n"]
        for r in results:
            # Each report may have multiple devices; grab the first
            devices = r.get("device", [{}])
            dev = devices[0] if devices else {}
            mdr_text = r.get("mdr_text", [{}])
            narrative = mdr_text[0].get("text", "No narrative") if mdr_text else "No narrative"
            lines.append(
                f"- [{r.get('date_received', 'N/A')}] "
                f"Brand: {dev.get('brand_name', 'N/A')} | "
                f"Event type: {r.get('event_type', 'N/A')} | "
                f"Outcome: {r.get('patient', [{}])[0].get('sequence_number_outcome', 'N/A') if r.get('patient') else 'N/A'} | "
                f"Narrative: {narrative[:200]}"
            )
        return "\n".join(lines)
    except requests.HTTPError as e:
        return f"OpenFDA adverse event API error: {e}"
    except Exception as e:
        return f"Unexpected error querying adverse events: {e}"


# ── 3. Device Classifications ────────────────────────────────────────────────

def get_device_classifications(device_name: str) -> str:
    """Query OpenFDA device classification endpoint."""
    url = f"{OPENFDA_BASE}/device/classification.json"
    params = {
        "search": f'device_name:"{device_name}"',
        "limit": 5,
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
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
    except requests.HTTPError as e:
        return f"OpenFDA classification API error: {e}"
    except Exception as e:
        return f"Unexpected error querying classifications: {e}"


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
