"""Offline HTTP API and source tests for pollutant event impact and CO2 endpoints."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sys
import urllib.parse

import numpy as np
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import event as event_mod
from app import main as main_mod
from app.event import EventSeriesInput
from app.main import app
from app.models import Co2GlobalSummary, Co2ImpactResult, Compound, EventResult
from app.sources import SourceUnavailable, giovanni, pollutants

client = TestClient(app)

SASAN = {"place_id": "test:sasan", "name": "Sasan UMPP, India", "lat": 23.98, "lon": 82.63}


def _seed_cache(tmp_path: Path, url: str, params: dict | None, content: str, ext: str = "json") -> Path:
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    key = hashlib.sha1(full.encode()).hexdigest()[:16]
    cdir = tmp_path / "cache"
    cdir.mkdir(parents=True, exist_ok=True)
    target = cdir / f"{key}.{ext}"
    target.write_text(content, encoding="utf-8")
    return target


def _synthetic_monthly(
    start_year: int,
    end_year: int,
    *,
    base: float = 5.0,
    amp: float = 1.5,
    step_month: str | None = None,
    step_size: float = 0.0,
    sd: float = 0.25,
    seed: int = 1,
):
    rng = np.random.default_rng(seed)
    months = [f"{y:04d}-{m:02d}" for y in range(start_year, end_year + 1) for m in range(1, 13)]
    vals = []
    step_active = False
    for idx, ym in enumerate(months):
        if step_month is not None and ym == step_month:
            step_active = True
        v = base + amp * math.sin(2.0 * math.pi * (idx % 12) / 12.0) + float(rng.normal(0.0, sd))
        if step_active:
            v += step_size
        vals.append(round(v, 4))
    return months, vals


@pytest.fixture
def fake_event_sources(monkeypatch: pytest.MonkeyPatch):
    calls: dict[str, object] = {}

    def fake_fetch_event(compound, lat, lon, *, use_control=True):
        calls["event"] = (compound.id, lat, lon, use_control)
        months, site = _synthetic_monthly(
            compound.first_year,
            compound.last_year,
            base=6.0,
            step_month="2015-01",
            step_size=2.5,
            seed=101,
        )
        ctrl = None
        if use_control:
            _, ctrl = _synthetic_monthly(
                compound.first_year,
                compound.last_year,
                base=4.0,
                seed=102,
            )
        return EventSeriesInput(
            months=months,
            site=site,
            control=ctrl,
            start=f"{compound.first_year:04d}-01",
            url="https://api.giovanni.earthdata.nasa.gov/timeseries?data=TEST",
            retrieved_at="2026-11-14T00:00:00Z",
        )

    def fake_fetch_co2():
        months = [f"{y:04d}-{m:02d}" for y in range(1980, 2026) for m in range(1, 13)]
        vals = [round(338.0 + 2.0 * (i / 12.0), 2) for i in range(len(months))]
        return {
            "months": months,
            "values": vals,
            "url": pollutants.NOAA_CO2_URL,
        }

    monkeypatch.setattr(event_mod, "fetch_event_series", fake_fetch_event)
    monkeypatch.setattr(event_mod, "fetch_global_co2_series", fake_fetch_co2)
    return calls


def test_compounds_whitelist():
    r = client.get("/api/compounds")
    assert r.status_code == 200
    items = [Compound.model_validate(item) for item in r.json()]
    by_id = {c.id: c for c in items}
    assert {"no2", "so2", "aod", "co2"} <= set(by_id)
    assert by_id["no2"].local_signal is True
    assert by_id["co2"].local_signal is False
    assert all(c.units and c.definition and c.product for c in items)


def test_event_happy_path_and_no_control(fake_event_sources):
    payload = {
        "compound_id": "no2",
        "place": SASAN,
        "event_month": "2015-01",
        "event_label": "Plant opening",
        "window_years": 3,
        "use_control": True,
    }
    r = client.post("/api/event", json=payload)
    assert r.status_code == 200, r.text
    res = EventResult.model_validate(r.json())
    assert res.verdict == "clear_change"
    assert res.direction == "increase"
    assert res.reason == "clear_change"
    assert res.control is not None
    assert len(res.steps) == 7
    assert [s.id for s in res.steps] == ["data", "seasons", "control", "before_after", "chance", "placebo", "verdict"]
    assert fake_event_sources["event"] == ("no2", 23.98, 82.63, True)

    r2 = client.post("/api/event", json={**payload, "use_control": False})
    assert r2.status_code == 200, r2.text
    res2 = EventResult.model_validate(r2.json())
    assert res2.control is None
    assert res2.verdict == "clear_change"


def test_event_error_handling(monkeypatch: pytest.MonkeyPatch):
    base = {
        "compound_id": "no2",
        "place": SASAN,
        "event_month": "2015-01",
        "event_label": "Test",
    }
    r_unk = client.post("/api/event", json={**base, "compound_id": "methane_fake"})
    assert r_unk.status_code == 400 and r_unk.json()["error"]["code"] == "unknown_variable"

    r_rng = client.post("/api/event", json={**base, "event_month": "1995-01"})
    assert r_rng.status_code == 400 and r_rng.json()["error"]["code"] == "bad_request"

    r_bad = client.post("/api/event", json={"compound_id": "no2"})
    assert r_bad.status_code == 400 and r_bad.json()["error"]["code"] == "bad_request"

    def boom(*a, **k):
        raise SourceUnavailable("giovanni", "offline")

    monkeypatch.setattr(event_mod, "fetch_event_series", boom)
    r_503 = client.post("/api/event", json=base)
    assert r_503.status_code == 503 and r_503.json()["error"]["code"] == "source_unavailable"


def test_co2_endpoints(fake_event_sources):
    rg = client.get("/api/co2/global")
    assert rg.status_code == 200, rg.text
    g = Co2GlobalSummary.model_validate(rg.json())
    assert g.latest_month == "2025-12"
    assert g.yoy_growth_ppm == pytest.approx(2.0, abs=0.05)
    assert g.sen_slope_ppm_per_year == pytest.approx(2.0, abs=0.05)

    ri = client.post(
        "/api/co2-impact",
        json={"mt_co2_per_year": 10.0, "years": 30, "what_if_ppm": 560.0, "label": "Coal plant"},
    )
    assert ri.status_code == 200, ri.text
    imp = Co2ImpactResult.model_validate(ri.json())
    assert imp.total_emitted_gt == pytest.approx(0.3)
    assert imp.what_if_forcing_w_m2 == pytest.approx(5.35 * math.log(2.0), abs=0.01)
    assert imp.transient_warming_c.central > 0.0


def test_events_showcase_endpoints(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_event_sources):
    # Generate one valid EventResult via the endpoint and save to a temporary EVENTS_DIR
    r = client.post(
        "/api/event",
        json={
            "compound_id": "no2",
            "place": SASAN,
            "event_month": "2015-01",
            "event_label": "Demo plant",
            "window_years": 3,
        },
    )
    assert r.status_code == 200
    ev_dir = tmp_path / "events"
    ev_dir.mkdir(parents=True)
    (ev_dir / "demo-plant.json").write_text(json.dumps(r.json()), encoding="utf-8")
    monkeypatch.setattr(main_mod, "EVENTS_DIR", ev_dir)

    r_list = client.get("/api/events")
    assert r_list.status_code == 200
    assert r_list.json()[0]["id"] == "demo-plant"

    r_one = client.get("/api/events/demo-plant")
    assert r_one.status_code == 200
    EventResult.model_validate(r_one.json())

    assert client.get("/api/events/missing").status_code == 404


def test_real_showcase_events_validate_and_serve_offline():
    events_dir = Path(__file__).resolve().parent.parent.parent / "data" / "events"
    files = sorted(events_dir.glob("*.json"))
    expected = {"burshtyn-aod.json", "la-no2-lockdown.json", "mundra-so2.json", "sasan-no2.json"}
    assert expected.issubset({p.name for p in files})

    for path in files:
        model = EventResult.model_validate(json.loads(path.read_text(encoding="utf-8")))
        assert len(model.steps) == 7
        for prov in model.provenance:
            assert "Bearer" not in prov.url

    r_list = client.get("/api/events")
    assert r_list.status_code == 200
    ids = {item["id"] for item in r_list.json()}
    assert {"burshtyn-aod", "la-no2-lockdown", "mundra-so2", "sasan-no2"} <= ids
    for eid in ("mundra-so2", "sasan-no2", "la-no2-lockdown", "burshtyn-aod"):
        one = client.get(f"/api/events/{eid}")
        assert one.status_code == 200
        EventResult.model_validate(one.json())


def test_giovanni_daily_aggregation_and_control_ring_offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EV_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OFFLINE", "1")
    monkeypatch.setenv("EARTHDATA_TOKEN", "super-secret-token")

    endpoint = f"{giovanni.GIOVANNI_URL}/timeseries"
    var_id = giovanni.GIOVANNI_VARS["no2"][0]

    def make_csv(lat: float, lon: float, jan_days: int, jan_val: float, feb_days: int, feb_val: float) -> str:
        lines = [
            "prod_name,OMNO2d.003",
            "unit,molecules/cm^2",
            "undef,-1.26765e+30",
            f"lat,{lat}",
            f"lon,{lon}",
            "",
            "Timestamp (UTC),Data",
        ]
        for d in range(1, jan_days + 1):
            lines.append(f"2020-01-{d:02d} 00:00,{jan_val:.4e}")
        for d in range(1, feb_days + 1):
            lines.append(f"2020-02-{d:02d} 00:00,{feb_val:.4e}")
        return "\n".join(lines)

    site_lat, site_lon = 30.0, 50.0
    _seed_cache(
        tmp_path,
        endpoint,
        {"data": var_id, "location": f"[{site_lat},{site_lon}]", "time": "2020-01-01T00:00:00/2020-12-31T23:59:59"},
        make_csv(site_lat, site_lon, 12, 10e15, 8, 20e15),  # Jan >=10d valid, Feb <10d -> None
        ext="csv",
    )

    ring = pollutants.control_ring_points(site_lat, site_lon)
    assert len(ring) == 8
    for idx, (_, rlat, rlon) in enumerate(ring):
        # 6 points valid in Jan (>=5), only 4 points valid in Feb (<5 -> control None)
        jan_d = 12 if idx < 6 else 5
        feb_d = 12 if idx < 4 else 5
        _seed_cache(
            tmp_path,
            endpoint,
            {"data": var_id, "location": f"[{rlat},{rlon}]", "time": "2020-01-01T00:00:00/2020-12-31T23:59:59"},
            make_csv(rlat, rlon, jan_d, 4e15, feb_d, 4e15),
            ext="csv",
        )

    res = pollutants.fetch_site_and_control("no2", site_lat, site_lon, 2020, 2020)
    assert res["site"][0] == pytest.approx(10.0)
    assert res["site"][1] is None  # only 8 valid days < 10
    assert res["control"] is not None
    assert res["control"][0] == pytest.approx(4.0)  # 6/8 valid points >= 5
    assert res["control"][1] is None  # only 4/8 valid points < 5
    assert "super-secret-token" not in res["url"]
    assert all("super-secret-token" not in u for u in res["control_urls"])
