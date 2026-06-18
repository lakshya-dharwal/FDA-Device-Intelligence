"""
Normalized response schemas for OpenFDA tool results.
"""

from src.backend.query_normalization import format_iso_date, normalize_search_term


def truncate_text(value: str | None, *, limit: int = 240) -> str | None:
    """Trim large text fields to a consistent size."""
    if not value:
        return None
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def build_tool_response(
    *,
    tool_name: str,
    query: str,
    normalized_terms: list[str],
    filters: dict,
    results: list[dict],
    search_fields: list[str],
) -> dict:
    """Return a structured tool payload for model consumption."""
    return {
        "tool": tool_name,
        "query": query,
        "normalized_terms": normalized_terms,
        "filters": filters,
        "search_fields": search_fields,
        "result_count": len(results),
        "results": results,
    }


def normalize_recall_result(record: dict) -> dict:
    """Map a raw OpenFDA recall record to a stable internal schema."""
    return {
        "record_id": record.get("res_event_number")
        or "|".join(
            [
                str(record.get("recalling_firm", "")),
                str(record.get("product_description", "")),
                str(record.get("recall_initiation_date", "")),
            ]
        ),
        "recall_initiation_date": format_iso_date(record.get("recall_initiation_date")),
        "classification": record.get("classification"),
        "product_description": truncate_text(record.get("product_description"), limit=180),
        "reason_for_recall": truncate_text(record.get("reason_for_recall"), limit=220),
        "recalling_firm": record.get("recalling_firm"),
        "product_code": record.get("product_code"),
        "distribution_pattern": truncate_text(record.get("distribution_pattern"), limit=160),
    }


def normalize_adverse_event_result(record: dict) -> dict:
    """Map a raw MAUDE event record to a stable internal schema."""
    devices = record.get("device") or [{}]
    primary_device = devices[0] if devices else {}
    patient = (record.get("patient") or [{}])[0]
    mdr_text = (record.get("mdr_text") or [{}])[0]

    return {
        "record_id": record.get("mdr_report_key")
        or record.get("report_number")
        or "|".join(
            [
                str(record.get("date_received", "")),
                str(primary_device.get("brand_name", "")),
                str(record.get("event_type", "")),
            ]
        ),
        "date_received": format_iso_date(record.get("date_received")),
        "event_type": record.get("event_type"),
        "brand_name": primary_device.get("brand_name"),
        "generic_name": primary_device.get("generic_name"),
        "manufacturer_name": primary_device.get("manufacturer_d_name"),
        "patient_outcome": patient.get("sequence_number_outcome"),
        "narrative": truncate_text(mdr_text.get("text"), limit=280),
    }


def normalize_classification_result(record: dict) -> dict:
    """Map a raw classification record to a stable internal schema."""
    return {
        "record_id": record.get("product_code")
        or "|".join(
            [
                str(record.get("device_name", "")),
                str(record.get("regulation_number", "")),
            ]
        ),
        "device_name": record.get("device_name"),
        "device_class": record.get("device_class"),
        "regulation_number": record.get("regulation_number"),
        "product_code": record.get("product_code"),
        "medical_specialty_description": record.get("medical_specialty_description"),
        "definition": truncate_text(record.get("definition"), limit=220),
    }


def score_recall_result(result: dict, terms: list[str]) -> int:
    """Score a recall result by match quality."""
    return _score_fields(
        result,
        terms,
        {
            "product_description": 5,
            "reason_for_recall": 3,
            "recalling_firm": 1,
        },
    )


def score_adverse_event_result(result: dict, terms: list[str]) -> int:
    """Score an adverse event result by match quality."""
    return _score_fields(
        result,
        terms,
        {
            "brand_name": 5,
            "generic_name": 4,
            "manufacturer_name": 2,
            "narrative": 1,
        },
    )


def score_classification_result(result: dict, terms: list[str]) -> int:
    """Score a classification result by match quality."""
    return _score_fields(
        result,
        terms,
        {
            "device_name": 5,
            "definition": 2,
            "medical_specialty_description": 1,
        },
    )


def sort_results(results: list[dict], *, date_key: str | None = None) -> list[dict]:
    """Sort records by score and optional date."""
    def sort_key(item: dict) -> tuple:
        date_value = item.get(date_key) if date_key else None
        return (
            item.get("_score", 0),
            date_value or "",
        )

    return sorted(results, key=sort_key, reverse=True)


def _score_fields(result: dict, terms: list[str], field_weights: dict[str, int]) -> int:
    score = 0
    for field_name, weight in field_weights.items():
        field_value = normalize_search_term(str(result.get(field_name) or ""))
        if not field_value:
            continue
        for term in terms:
            if term == field_value:
                score += weight * 3
            elif term in field_value:
                score += weight
    return score
