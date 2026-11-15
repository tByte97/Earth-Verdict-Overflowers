"""Offline tests for /api/parse-claim (Gemini and the geocoder are replaced by fakes)."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import llm, parse
from app.main import app
from app.sources import geocode

client = TestClient(app)
KYIV = {"place_id": "om:703448", "name": "Kyiv, Ukraine", "lat": 50.45, "lon": 30.52}


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch):
    parse._cache.clear()
    llm._calls.clear()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(geocode, "search_places", lambda q: [KYIV] if q.lower() in ("kyiv", "київ") else [])
    yield


def _fake(monkeypatch, reply: dict | str):
    calls = []

    def fake(key, model, prompt, system=llm.SYSTEM, json_out=False):
        calls.append((prompt, system, json_out))
        return reply if isinstance(reply, str) else json.dumps(reply)

    monkeypatch.setattr(llm, "_call_gemini", fake)
    return calls


def test_global_claim_maps_to_planet_from_claim_year(monkeypatch):
    calls = _fake(monkeypatch, {"variable_id": "global_temp", "place": None, "region": "globe", "season": "year",
                                "start_year": 1998, "end_year": None, "claim_direction": "decrease",
                                "notes": ["Stopped is checked as not rising: a clear rise refutes it."]})
    r = client.post("/api/parse-claim", json={"text": "потепління зупинилось після 1998"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["spec"] == {"claim_text": "потепління зупинилось після 1998", "variable_id": "global_temp",
                            "place": {"place_id": "region:globe", "name": "The whole planet", "lat": 0.0, "lon": 0.0},
                            "season": "year", "start_year": 1998, "end_year": 2025, "claim_direction": "decrease"}
    assert body["place_found"] is True and body["notes"]
    assert calls[0][2] is True and "global_temp" in calls[0][1]
    client.post("/api/parse-claim", json={"text": "потепління  зупинилось після 1998"})
    assert len(calls) == 1                      # same claim (spaces normalised) comes from the cache


def test_city_claim_is_geocoded_and_years_default_to_the_record(monkeypatch):
    _fake(monkeypatch, "```json\n" + json.dumps({"variable_id": "air_temp", "place": "Kyiv", "region": None, "season": "JJA",
                                                  "start_year": None, "end_year": None, "claim_direction": "increase", "notes": []}) + "\n```")
    body = client.post("/api/parse-claim", json={"text": "Summers in Kyiv are getting hotter"}).json()
    assert body["spec"]["place"] == KYIV and body["place_found"] is True
    assert (body["spec"]["season"], body["spec"]["start_year"], body["spec"]["end_year"]) == ("JJA", 1981, 2025)
    assert body["spec"]["claim_direction"] == "increase"


def test_unknown_place_and_out_of_range_years_are_flagged(monkeypatch):
    _fake(monkeypatch, {"variable_id": "precip", "place": "Atlantis", "season": "monsoon", "start_year": 1950,
                        "end_year": 2090, "claim_direction": "sideways", "notes": "not a list"})
    body = client.post("/api/parse-claim", json={"text": "Atlantis gets wetter since 1950"}).json()
    spec = body["spec"]
    assert body["place_found"] is False and body["place_query"] == "Atlantis"
    assert (spec["season"], spec["claim_direction"], spec["start_year"], spec["end_year"]) == ("year", "change", 1981, 2025)
    assert any("Atlantis" in n for n in body["notes"]) and any("1981" in n for n in body["notes"])


@pytest.mark.parametrize("reply", [{"variable_id": "sea_level"}, "no json here", "[1, 2]"])
def test_unusable_reply_is_a_clear_error(monkeypatch, reply):
    _fake(monkeypatch, reply)
    r = client.post("/api/parse-claim", json={"text": "Sea level is rising in Odesa"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "cannot_parse"


def test_without_a_key_the_parser_says_so(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.setattr(llm, "KEY_FILE", Path("/nonexistent/key"))
    r = client.post("/api/parse-claim", json={"text": "Kyiv is getting colder"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "llm_unavailable"


def test_too_short_text_is_rejected():
    assert client.post("/api/parse-claim", json={"text": "hi"}).status_code == 400


def test_one_outage_is_retried(monkeypatch):
    calls = []

    def flaky(key, model, prompt, system=llm.SYSTEM, json_out=False):
        calls.append(prompt)
        if len(calls) == 1:
            raise parse.CheckError("llm_unavailable", "The explanation service answered HTTP 503.")
        return json.dumps({"variable_id": "air_temp", "place": "Kyiv", "season": "year", "claim_direction": "decrease"})

    monkeypatch.setattr(llm, "_call_gemini", flaky)
    r = client.post("/api/parse-claim", json={"text": "Kyiv is getting colder"})
    assert r.status_code == 200 and len(calls) == 2
