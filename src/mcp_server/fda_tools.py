"""
FDA MCP Tools — three functions that query the public OpenFDA API.
Each function is also registered as an MCP tool so this file can run
as a standalone MCP server (called by Claude via the MCP protocol).
"""

from mcp.server.fastmcp import FastMCP
from src.backend.openfda_client import get_json
from src.backend.query_normalization import (
    build_date_filter_clause,
    build_text_search_clause,
    combine_search_clauses,
    format_iso_date,
    generate_search_variants,
)
from src.backend.result_schemas import (
    build_tool_response,
    normalize_adverse_event_result,
    normalize_classification_result,
    normalize_recall_result,
    score_adverse_event_result,
    score_classification_result,
    score_recall_result,
    sort_results,
)

# Initialise the FastMCP server (name shows up in Claude's tool list)
mcp = FastMCP("fda-device-intelligence")

RECALL_SEARCH_FIELDS = [
    "product_description",
    "reason_for_recall",
    "recalling_firm",
]
ADVERSE_EVENT_SEARCH_FIELDS = [
    "device.brand_name",
    "device.generic_name",
    "device.manufacturer_d_name",
]
CLASSIFICATION_SEARCH_FIELDS = [
    "device_name",
    "definition",
]


# ── 1. Device Recalls ────────────────────────────────────────────────────────

def search_device_recalls(
    search_term: str,
    limit: int = 10,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    """Query OpenFDA device recall endpoint and return structured results."""
    normalized_terms = generate_search_variants(search_term)
    params = {
        "search": combine_search_clauses(
            build_text_search_clause(RECALL_SEARCH_FIELDS, normalized_terms),
            build_date_filter_clause(
                "recall_initiation_date",
                date_from=date_from,
                date_to=date_to,
            ),
        ),
        "limit": max(limit * 3, 10),
    }
    data = get_json("/device/recall.json", params=params)
    records = _rank_and_limit_results(
        data.get("results", []),
        normalizer=normalize_recall_result,
        scorer=score_recall_result,
        terms=normalized_terms,
        limit=limit,
        date_key="recall_initiation_date",
    )
    return build_tool_response(
        tool_name="search_device_recalls",
        query=search_term,
        normalized_terms=normalized_terms,
        filters={
            "date_from": format_iso_date(date_from),
            "date_to": format_iso_date(date_to),
        },
        results=records,
        search_fields=RECALL_SEARCH_FIELDS,
    )


# ── 2. Adverse Events ────────────────────────────────────────────────────────

def get_adverse_events(
    device_name: str,
    limit: int = 10,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    """Query OpenFDA device adverse event (MAUDE) endpoint."""
    normalized_terms = generate_search_variants(device_name)
    params = {
        "search": combine_search_clauses(
            build_text_search_clause(ADVERSE_EVENT_SEARCH_FIELDS, normalized_terms),
            build_date_filter_clause(
                "date_received",
                date_from=date_from,
                date_to=date_to,
            ),
        ),
        "limit": max(limit * 3, 10),
    }
    data = get_json("/device/event.json", params=params)
    records = _rank_and_limit_results(
        data.get("results", []),
        normalizer=normalize_adverse_event_result,
        scorer=score_adverse_event_result,
        terms=normalized_terms,
        limit=limit,
        date_key="date_received",
    )
    return build_tool_response(
        tool_name="get_adverse_events",
        query=device_name,
        normalized_terms=normalized_terms,
        filters={
            "date_from": format_iso_date(date_from),
            "date_to": format_iso_date(date_to),
        },
        results=records,
        search_fields=ADVERSE_EVENT_SEARCH_FIELDS,
    )


# ── 3. Device Classifications ────────────────────────────────────────────────

def get_device_classifications(device_name: str, limit: int = 5) -> dict:
    """Query OpenFDA device classification endpoint."""
    normalized_terms = generate_search_variants(device_name)
    params = {
        "search": build_text_search_clause(
            CLASSIFICATION_SEARCH_FIELDS,
            normalized_terms,
        ),
        "limit": max(limit * 3, 10),
    }
    data = get_json("/device/classification.json", params=params)
    records = _rank_and_limit_results(
        data.get("results", []),
        normalizer=normalize_classification_result,
        scorer=score_classification_result,
        terms=normalized_terms,
        limit=limit,
        date_key=None,
    )
    return build_tool_response(
        tool_name="get_device_classifications",
        query=device_name,
        normalized_terms=normalized_terms,
        filters={},
        results=records,
        search_fields=CLASSIFICATION_SEARCH_FIELDS,
    )


def _rank_and_limit_results(
    raw_results: list[dict],
    *,
    normalizer,
    scorer,
    terms: list[str],
    limit: int,
    date_key: str | None,
) -> list[dict]:
    """Normalize, score, dedupe, and cap OpenFDA records."""
    deduped: dict[str, dict] = {}

    for record in raw_results:
        normalized = normalizer(record)
        normalized["_score"] = scorer(normalized, terms)
        record_id = normalized["record_id"]

        existing = deduped.get(record_id)
        if existing is None or normalized["_score"] > existing["_score"]:
            deduped[record_id] = normalized

    ranked = sort_results(list(deduped.values()), date_key=date_key)
    trimmed = ranked[:limit]
    for item in trimmed:
        item.pop("_score", None)
    return trimmed


# ── MCP tool wrappers ────────────────────────────────────────────────────────
# These decorators register the plain functions above as MCP tools.

@mcp.tool()
def mcp_search_device_recalls(
    search_term: str,
    limit: int = 10,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    """Search FDA device recalls by normalized device terms and optional dates."""
    return search_device_recalls(search_term, limit, date_from, date_to)


@mcp.tool()
def mcp_get_adverse_events(
    device_name: str,
    limit: int = 10,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    """Retrieve adverse event (MAUDE) reports for a device with optional date filters."""
    return get_adverse_events(device_name, limit, date_from, date_to)


@mcp.tool()
def mcp_get_device_classifications(device_name: str, limit: int = 5) -> dict:
    """Look up FDA device classification (class I/II/III) for a device name."""
    return get_device_classifications(device_name, limit)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
