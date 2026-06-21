"""
Helpers for normalizing user search terms and building OpenFDA query clauses.
"""

import re
from datetime import datetime

from src.backend.exceptions import InvalidQueryError

WHITESPACE_RE = re.compile(r"\s+")
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

SYNONYM_MAP = {
    "da vinci": ["davinci", "da vinci surgical robot", "surgical robot"],
    "glucose monitor": ["continuous glucose monitor", "cgm", "blood glucose monitor"],
    "continuous glucose monitor": ["glucose monitor", "cgm"],
    "pacemaker": ["cardiac pacemaker", "implantable pulse generator"],
    "infusion pump": ["infusion system", "iv pump"],
    "metal on metal hip implant": ["metal-on-metal hip implant", "hip implant"],
    "metal on metal hip implants": ["metal-on-metal hip implants", "hip implants"],
}


def normalize_search_term(value: str) -> str:
    """Lowercase and normalize whitespace/punctuation for search comparisons."""
    normalized = NON_ALNUM_RE.sub(" ", value.lower()).strip()
    return WHITESPACE_RE.sub(" ", normalized)


def generate_search_variants(query: str) -> list[str]:
    """Expand a user query into normalized search variants."""
    canonical = normalize_search_term(query)
    if not canonical:
        raise InvalidQueryError("Query term cannot be empty.")

    variants: list[str] = []

    def add_variant(candidate: str) -> None:
        normalized = normalize_search_term(candidate)
        if normalized and normalized not in variants:
            variants.append(normalized)

    add_variant(canonical)

    compact = canonical.replace(" ", "")
    if compact != canonical and len(compact) >= 6:
        add_variant(compact)

    for key, aliases in SYNONYM_MAP.items():
        if key in canonical or canonical in key:
            for alias in aliases:
                add_variant(alias)

    if len(canonical.split()) > 1:
        for token in canonical.split():
            if len(token) >= 4:
                add_variant(token)

    return variants[:6]


def normalize_openfda_date(value: str | None) -> str | None:
    """Normalize a date string into OpenFDA's YYYYMMDD format."""
    if not value:
        return None

    raw = value.strip()
    for pattern in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(raw, pattern).strftime("%Y%m%d")
        except ValueError:
            continue

    raise InvalidQueryError(
        f"Invalid date '{value}'. Use YYYY-MM-DD or YYYYMMDD."
    )


def format_iso_date(value: str | None) -> str | None:
    """Render an OpenFDA-style date as ISO YYYY-MM-DD when possible."""
    if not value:
        return None

    raw = value.strip()
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return raw


def build_text_search_clause(fields: list[str], terms: list[str]) -> str:
    """Build an OR clause across multiple fields and normalized terms."""
    clauses: list[str] = []
    for field in fields:
        for term in terms:
            escaped = term.replace('"', '\\"')
            clauses.append(f'{field}:"{escaped}"')
    return "(" + " OR ".join(clauses) + ")"


def build_date_filter_clause(
    field_name: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str | None:
    """Build an OpenFDA range filter clause for the given field."""
    normalized_from = normalize_openfda_date(date_from)
    normalized_to = normalize_openfda_date(date_to)

    if not normalized_from and not normalized_to:
        return None
    if normalized_from and normalized_to and normalized_from > normalized_to:
        raise InvalidQueryError("date_from cannot be later than date_to.")

    lower = normalized_from or "19000101"
    upper = normalized_to or "29991231"
    return f"{field_name}:[{lower} TO {upper}]"


def combine_search_clauses(*clauses: str | None) -> str:
    """Join non-empty OpenFDA clauses with AND."""
    active_clauses = [clause for clause in clauses if clause]
    return " AND ".join(active_clauses)
