import pytest

from src.backend.exceptions import FDAUpstreamError
from src.mcp_server import fda_tools


def test_search_device_recalls_returns_structured_results(monkeypatch):
    def fake_get_json(path, params):
        assert path == "/device/recall.json"
        assert params["limit"] == 10
        assert 'product_description:"infusion pump"' in params["search"]
        assert 'reason_for_recall:"iv pump"' in params["search"]
        assert "recall_initiation_date:[2024" in params["search"]
        return {
            "results": [
                {
                    "res_event_number": "R-1",
                    "recall_initiation_date": "20240601",
                    "recalling_firm": "Acme Medical",
                    "classification": "I",
                    "product_description": "Infusion Pump Model X",
                    "reason_for_recall": "Battery failure",
                }
            ]
        }

    monkeypatch.setattr(fda_tools, "get_json", fake_get_json)

    result = fda_tools.search_device_recalls(
        "infusion pump",
        limit=2,
        date_from="2024-01-01",
    )

    assert result["tool"] == "search_device_recalls"
    assert result["query"] == "infusion pump"
    assert result["filters"]["date_from"] == "2024-01-01"
    assert result["result_count"] == 1
    assert result["results"][0]["recalling_firm"] == "Acme Medical"
    assert result["results"][0]["reason_for_recall"] == "Battery failure"


def test_search_device_recalls_handles_no_results(monkeypatch):
    monkeypatch.setattr(
        fda_tools,
        "get_json",
        lambda path, params: {"results": []},
    )

    result = fda_tools.search_device_recalls("nonexistent device")

    assert result["query"] == "nonexistent device"
    assert result["result_count"] == 0
    assert result["results"] == []


def test_get_adverse_events_returns_structured_results(monkeypatch):
    monkeypatch.setattr(
        fda_tools,
        "get_json",
        lambda path, params: (
            {
                "results": [
                    {
                        "mdr_report_key": "MDR-1",
                        "date_received": "20240515",
                        "event_type": "Malfunction",
                        "device": [
                            {
                                "brand_name": "Robo Surgeon",
                                "generic_name": "Surgical Robot",
                            }
                        ],
                        "patient": [{"sequence_number_outcome": "Hospitalization"}],
                        "mdr_text": [{"text": "Narrative details go here."}],
                    }
                ]
            }
            if 'device.brand_name:"da vinci"' in params["search"]
            else {"results": []}
        ),
    )

    result = fda_tools.get_adverse_events("da Vinci", limit=1)

    assert result["normalized_terms"][:2] == ["da vinci", "davinci"]
    assert result["result_count"] == 1
    assert result["results"][0]["brand_name"] == "Robo Surgeon"
    assert result["results"][0]["narrative"] == "Narrative details go here."


def test_get_device_classifications_returns_structured_results(monkeypatch):
    monkeypatch.setattr(
        fda_tools,
        "get_json",
        lambda path, params: {
            "results": [
                {
                    "product_code": "DXY",
                    "device_name": "Pacemaker",
                    "device_class": "3",
                    "regulation_number": "870.3610",
                    "medical_specialty_description": "Cardiovascular",
                }
            ]
        },
    )

    result = fda_tools.get_device_classifications("pacemaker")

    assert result["tool"] == "get_device_classifications"
    assert result["result_count"] == 1
    assert result["results"][0]["device_class"] == "3"
    assert result["results"][0]["product_code"] == "DXY"


def test_get_device_classifications_propagates_upstream_errors(monkeypatch):
    def fake_get_json(path, params):
        raise FDAUpstreamError("The FDA data source returned an error.")

    monkeypatch.setattr(fda_tools, "get_json", fake_get_json)

    with pytest.raises(FDAUpstreamError):
        fda_tools.get_device_classifications("pacemaker")


def test_get_device_classifications_dedupes_and_ranks_results(monkeypatch):
    monkeypatch.setattr(
        fda_tools,
        "get_json",
        lambda path, params: {
            "results": [
                {
                    "product_code": "ABC",
                    "device_name": "General Cardiac Device",
                    "device_class": "2",
                    "regulation_number": "000.0000",
                    "definition": "General device definition.",
                },
                {
                    "product_code": "DXY",
                    "device_name": "Cardiac Pacemaker",
                    "device_class": "3",
                    "regulation_number": "870.3610",
                    "definition": "Cardiac pacemaker implantable pulse generator.",
                },
                {
                    "product_code": "DXY",
                    "device_name": "Cardiac Pacemaker",
                    "device_class": "3",
                    "regulation_number": "870.3610",
                    "definition": "Duplicate higher quality row.",
                },
            ]
        },
    )

    result = fda_tools.get_device_classifications("pacemaker", limit=2)

    assert result["result_count"] == 2
    assert result["results"][0]["product_code"] == "DXY"
    assert result["results"][1]["product_code"] == "ABC"
