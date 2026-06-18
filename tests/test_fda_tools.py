"""
Unit tests for the OpenFDA tool functions.

All HTTP is mocked via the FakeResponse fixture, so these tests exercise our
parsing, error handling, and input-guard logic without touching the network.
"""

from __future__ import annotations

import requests

from src.mcp_server import fda_tools
from tests.conftest import FakeResponse


def _patch_get(monkeypatch, response):
    """Patch requests.get inside fda_tools to return a fixed response."""
    monkeypatch.setattr(fda_tools.requests, "get", lambda *a, **k: response)


# ── search_device_recalls ─────────────────────────────────────────────────────

def test_recalls_formats_results(monkeypatch):
    payload = {"results": [{
        "recall_initiation_date": "20230101",
        "recalling_firm": "Acme Medical",
        "classification": "Class I",
        "product_description": "Infusion pump model X",
        "reason_for_recall": "Battery may fail",
    }]}
    _patch_get(monkeypatch, FakeResponse(json_data=payload))
    out = fda_tools.search_device_recalls("infusion pump")
    assert "Acme Medical" in out
    assert "Class I" in out
    assert "Found 1 recall(s)" in out


def test_recalls_empty_results(monkeypatch):
    _patch_get(monkeypatch, FakeResponse(json_data={"results": []}))
    out = fda_tools.search_device_recalls("nonexistent device")
    assert "No recalls found" in out


def test_recalls_404_is_treated_as_empty(monkeypatch):
    _patch_get(monkeypatch, FakeResponse(json_data={}, status_code=404))
    out = fda_tools.search_device_recalls("obscure")
    assert "No recalls found" in out


def test_recalls_timeout(monkeypatch):
    def _raise(*a, **k):
        raise requests.Timeout()
    monkeypatch.setattr(fda_tools.requests, "get", _raise)
    out = fda_tools.search_device_recalls("infusion pump")
    assert "timed out" in out.lower()


def test_recalls_connection_error(monkeypatch):
    def _raise(*a, **k):
        raise requests.ConnectionError()
    monkeypatch.setattr(fda_tools.requests, "get", _raise)
    out = fda_tools.search_device_recalls("infusion pump")
    assert "could not connect" in out.lower()


def test_recalls_http_error(monkeypatch):
    resp = FakeResponse(status_code=500, raise_exc=requests.HTTPError("500 Server Error"))
    _patch_get(monkeypatch, resp)
    out = fda_tools.search_device_recalls("infusion pump")
    assert "error" in out.lower()


# ── get_adverse_events ────────────────────────────────────────────────────────

def test_adverse_events_formats_results(monkeypatch):
    payload = {"results": [{
        "date_received": "20220601",
        "event_type": "Malfunction",
        "device": [{"brand_name": "CardioPace"}],
        "mdr_text": [{"text": "Device stopped pacing."}],
        "patient": [{"sequence_number_outcome": "Hospitalization"}],
    }]}
    _patch_get(monkeypatch, FakeResponse(json_data=payload))
    out = fda_tools.get_adverse_events("CardioPace")
    assert "CardioPace" in out
    assert "Malfunction" in out


def test_adverse_events_handles_missing_nested_fields(monkeypatch):
    # No device/mdr_text/patient keys — must not raise.
    payload = {"results": [{"date_received": "20220601", "event_type": "Injury"}]}
    _patch_get(monkeypatch, FakeResponse(json_data=payload))
    out = fda_tools.get_adverse_events("MysteryDevice")
    assert "Injury" in out
    assert "N/A" in out


def test_adverse_events_empty(monkeypatch):
    _patch_get(monkeypatch, FakeResponse(json_data={"results": []}))
    out = fda_tools.get_adverse_events("nothing")
    assert "No adverse events found" in out


# ── get_device_classifications ────────────────────────────────────────────────

def test_classifications_formats_results(monkeypatch):
    payload = {"results": [{
        "device_name": "Pacemaker",
        "device_class": "3",
        "regulation_number": "870.3610",
        "product_code": "LWP",
        "medical_specialty_description": "Cardiovascular",
    }]}
    _patch_get(monkeypatch, FakeResponse(json_data=payload))
    out = fda_tools.get_device_classifications("Pacemaker")
    assert "Pacemaker" in out
    assert "870.3610" in out
    assert "Cardiovascular" in out


def test_classifications_empty(monkeypatch):
    _patch_get(monkeypatch, FakeResponse(json_data={"results": []}))
    out = fda_tools.get_device_classifications("nothing")
    assert "No classification data found" in out


# ── input guards ──────────────────────────────────────────────────────────────

def test_clamp_limit_bounds():
    assert fda_tools._clamp_limit(-5) == 1
    assert fda_tools._clamp_limit(0) == 1
    assert fda_tools._clamp_limit(5000) == 1000
    assert fda_tools._clamp_limit(10) == 10
    assert fda_tools._clamp_limit("not a number") == 10


def test_escape_quotes():
    assert fda_tools._escape('a "quoted" term') == 'a \\"quoted\\" term'
    assert fda_tools._escape(None) == ""


def test_malformed_json_response(monkeypatch):
    resp = FakeResponse(json_data=ValueError("bad json"))
    _patch_get(monkeypatch, resp)
    out = fda_tools.search_device_recalls("infusion pump")
    assert "unreadable" in out.lower()
