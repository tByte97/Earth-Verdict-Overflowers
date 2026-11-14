"""HTTP API tests. Offline: data sources are replaced with synthetic monthly series."""
from pathlib import Path
import sys

import numpy as np
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import check as check_mod
from app.check import MainSeries, StationInput
from app.main import app
from app.models import CheckResult

client = TestClient(app)

KYIV = {"place_id": "om:703448", "name": "Kyiv, Ukraine", "lat": 50.45, "lon": 30.52}


def spec(**over):
    s = {"claim_text": "Summers in Kyiv are getting hotter", "variable_id": "air_temp", "place": KYIV,
         "season": "JJA", "start_year": 1981, "end_year": 2025, "claim_direction": "increase"}
    s.update(over)
    return s


def monthly(slope_per_year, seed, start=1980, end=2025, base=8.0, amp=12.0, sd=0.8):
    """Seasonal cycle + trend + noise, January `start` .. December `end`."""
    rng = np.random.default_rng(seed)
    out = []
    for y in range(start, end + 1):
        for m in range(1, 13):
            out.append(float(base - amp * np.cos(2 * np.pi * (m - 1) / 12) + slope_per_year * (y - start)
                             + rng.normal(0, sd)))
    return out


@pytest.fixture
def fake_sources(monkeypatch):
    calls = {}

    def main_series(var, lat, lon, start, end):
        calls["main"] = (var.id, lat, lon, start, end)
        return MainSeries(monthly=monthly(0.06, 1), start="1980-01", url="https://power.example/test",
                          retrieved_at="2026-11-14T00:00:00Z")

    def station(var, lat, lon, start, end):
        calls["station"] = (var.witness, start, end)
        vals = monthly(0.07, 2)
        vals[(2006 - 1980) * 12:(2022 - 1980) * 12] = [None] * (16 * 12)   # Kyiv-like gap 2006–2021
        return StationInput(id="UPM00033345", name="KIEV, UP", lat=50.4, lon=30.57, distance_km=6,
                            monthly=vals, start="1980-01", method="ghcnd-daily-mean",
                            url="https://noaa.example/test", retrieved_at="2026-11-14T00:00:00Z")

    monkeypatch.setattr(check_mod, "fetch_main_series", main_series)
    monkeypatch.setattr(check_mod, "fetch_station", station)
    return calls


def test_health():
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_variables_whitelist():
    r = client.get("/api/variables")
    assert r.status_code == 200
    ids = {v["id"] for v in r.json()}
    assert {"air_temp", "precip", "snow_depth", "precip_gpm"} <= ids
    assert all(v["units"] and v["definition"] for v in r.json())


def test_check_happy_path(fake_sources):
    r = client.post("/api/check", json=spec())
    assert r.status_code == 200, r.text
    res = CheckResult.model_validate(r.json())
    assert res.verdict == "confirmed" and res.reason == "significant_trend"
    assert res.witness is not None and res.witness.station.name == "Kyiv"
    assert sum(p.value is None for p in res.witness.series) == 16
    assert res.meta.stub is False
    assert [s.id for s in res.steps][0] == "raw" and len(res.steps) == 8
    assert fake_sources["main"][0] == "air_temp" and fake_sources["station"][0] == "TAVG"


def test_check_djf_starts_a_year_later(fake_sources):
    r = client.post("/api/check", json=spec(season="DJF"))
    assert r.status_code == 200, r.text
    assert r.json()["case"]["start_year"] == 1982


def test_unknown_variable():
    r = client.post("/api/check", json=spec(variable_id="unicorns"))
    assert r.status_code == 400 and r.json()["error"]["code"] == "unknown_variable"


def test_short_series():
    r = client.post("/api/check", json=spec(start_year=2015))
    assert r.status_code == 400 and r.json()["error"]["code"] == "short_series"


def test_years_outside_source():
    r = client.post("/api/check", json=spec(variable_id="precip_gpm", start_year=1981))
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_request"


def test_malformed_request():
    r = client.post("/api/check", json={"claim_text": "x"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_request"


def test_source_unavailable(monkeypatch):
    from app.sources import SourceUnavailable

    def boom(*a, **k):
        raise SourceUnavailable("power", "timeout")

    monkeypatch.setattr(check_mod, "fetch_main_series", boom)
    r = client.post("/api/check", json=spec())
    assert r.status_code == 503 and r.json()["error"]["code"] == "source_unavailable"


def test_station_failure_is_not_fatal(fake_sources, monkeypatch):
    from app.sources import SourceUnavailable

    def boom(*a, **k):
        raise SourceUnavailable("noaa", "timeout")

    monkeypatch.setattr(check_mod, "fetch_station", boom)
    r = client.post("/api/check", json=spec())
    assert r.status_code == 200 and r.json()["witness"] is None


def test_cases_offline():
    r = client.get("/api/cases")
    assert r.status_code == 200
    ids = {c["id"] for c in r.json()}
    assert {"kyiv-summer-heat", "lviv-drier", "kyiv-winter-snow"} <= ids
    one = client.get("/api/cases/kyiv-summer-heat")
    assert one.status_code == 200 and CheckResult.model_validate(one.json()).verdict == "confirmed"
    assert client.get("/api/cases/nope").status_code == 404


def test_grid_layer():
    r = client.get("/api/grid", params={"variable_id": "precip", "season": "JJA"})
    assert r.status_code == 200
    gj = r.json()
    assert gj["type"] == "FeatureCollection" and len(gj["features"]) > 100


def test_places_short_query_is_empty():
    assert client.get("/api/places", params={"q": "K"}).json() == []


def test_live_check_reuses_nearby_cmip6(fake_sources):
    r = client.post("/api/check", json=spec())
    sc = r.json()["scenarios"]
    assert sc is not None and sc["synthetic"] is False
    assert [p["id"] for p in sc["paths"]] == ["ssp126", "ssp245", "ssp585"]
    assert sc["baseline_value"] is not None
    assert any(p["source"] == "NASA NCCS" for p in r.json()["provenance"])


def test_no_scenarios_far_away_or_for_other_variables(fake_sources):
    far = dict(KYIV, place_id="x", name="Somewhere", lat=10.0, lon=10.0)
    assert client.post("/api/check", json=spec(place=far)).json()["scenarios"] is None
    assert client.post("/api/check", json=spec(variable_id="snow_depth", season="DJF")).json()["scenarios"] is None
