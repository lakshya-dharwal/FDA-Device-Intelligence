import pytest

from src.backend.exceptions import InvalidQueryError
from src.backend.query_normalization import (
    build_date_filter_clause,
    build_text_search_clause,
    combine_search_clauses,
    generate_search_variants,
    normalize_openfda_date,
)


def test_generate_search_variants_expands_common_aliases():
    variants = generate_search_variants("Da Vinci")

    assert variants[:3] == ["da vinci", "davinci", "da vinci surgical robot"]


def test_build_date_filter_clause_normalizes_date_range():
    clause = build_date_filter_clause(
        "date_received",
        date_from="2024-01-01",
        date_to="20240131",
    )

    assert clause == "date_received:[20240101 TO 20240131]"


def test_build_date_filter_clause_rejects_invalid_ranges():
    with pytest.raises(InvalidQueryError):
        build_date_filter_clause(
            "date_received",
            date_from="2024-02-01",
            date_to="2024-01-01",
        )


def test_build_text_search_clause_joins_fields_and_terms():
    clause = build_text_search_clause(
        ["device_name", "definition"],
        ["pacemaker", "implantable pulse generator"],
    )

    assert 'device_name:"pacemaker"' in clause
    assert 'definition:"implantable pulse generator"' in clause
    assert clause.startswith("(")


def test_combine_search_clauses_skips_empty_values():
    combined = combine_search_clauses(
        build_text_search_clause(["device_name"], ["pacemaker"]),
        None,
        "date_received:[20240101 TO 20240131]",
    )

    assert " AND " in combined
    assert normalize_openfda_date("2024-01-01") == "20240101"
