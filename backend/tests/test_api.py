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

    def main_series(var, lat, lon):
        calls["main"] = (var.id, lat, lon)
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
    by_id = {v["id"]: v for v in r.json()}
    assert {"air_temp", "precip", "snow_depth", "precip_gpm"} <= set(by_id)
    assert all(v["units"] and v["definition"] for v in by_id.values())
    assert (by_id["air_temp"]["first_year"], by_id["air_temp"]["last_year"]) == (1981, 2025)
    assert (by_id["precip_gpm"]["first_year"], by_id["precip_gpm"]["last_year"]) == (1998, 2024)
    assert (by_id["global_temp"]["first_year"], by_id["global_temp"]["last_year"]) == (1850, 2025)


def test_check_happy_path(fake_sources):
    r = client.post("/api/check", json=spec())
    assert r.status_code == 200, r.text
    res = CheckResult.model_validate(r.json())
    assert res.verdict == "confirmed" and res.reason == "significant_trend"
    assert res.witness is not None and res.witness.station.name == "Kyiv"
    assert sum(p.value is None for p in res.witness.series) == 16
    assert res.meta.stub is False
    assert res.detection_history is not None
    assert res.detection_history.points[-1].n_observations == res.detection.n_years
    assert float(f'{res.detection_history.points[-1].p:.3g}') == res.mk.p
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
    assert gj["variable_id"] == "precip" and gj["start_year"] == 1981 and gj["end_year"] == 2025
    assert gj["stats_engine"] and gj["n_cells"] >= gj["n_significant_raw"] >= gj["n_significant_fdr"]
    pairs = [client.get("/api/grid", params={"variable_id": "precip", "season": s}).json()["pair"]
             for s in ("JJA", "DJF", "year")]
    for pair in filter(None, pairs):
        assert pair["a"]["slope_per_decade"] > 0 > pair["b"]["slope_per_decade"]
        assert pair["significance"] in ("fdr", "raw")
    djf = client.get("/api/grid", params={"variable_id": "air_temp", "season": "DJF"}).json()
    assert djf["start_year"] == 1982 and djf["variable_id"] == "air_temp"


def test_grid_layer_counts_match_features():
    for season in ("year", "JJA", "DJF"):
        gj = client.get("/api/grid", params={"variable_id": "precip", "season": season}).json()
        halo = [f["properties"] for f in gj["features"] if f["properties"].get("halo")]
        props = [f["properties"] for f in gj["features"] if not f["properties"].get("halo")]
        # The halo is drawn around the tested area and stays out of every count.
        assert len(halo) > 100 and gj["halo_cells"] >= 3 and all(f["geometry"] is None for f in gj["features"] if f["properties"].get("halo"))
        assert gj["n_cells"] == sum(p["p"] is not None for p in props)
        assert gj["n_significant_fdr"] == sum(p["significant_fdr"] for p in props)
        assert gj["n_significant_raw"] == sum(p["significant_raw"] for p in props)
        assert gj["n_significant_fdr"] <= gj["n_significant_raw"] <= gj["n_cells"]


def test_grid_years_serves_year_by_year_maps(monkeypatch, tmp_path):
    from app import main
    r = client.get("/api/grid/years", params={"variable_id": "air_temp", "season": "DJF"})
    assert r.status_code == 200
    m = r.json()
    assert (m["variable_id"], m["season"], m["units"], m["baseline"]) == ("air_temp", "DJF", "°C", [1991, 2020])
    assert m["years"][0] == 1982 and m["years"][-1] == 2025          # a winter is named by its January
    n_years, n_cells = len(m["years"]), len(m["lat"])
    assert n_cells == len(m["lon"]) > 100
    for rows in (m["anomaly"], m["anomaly_smooth"]):
        assert len(rows) == n_years and all(len(row) == n_cells for row in rows)
    assert len(m["mean"]) == len(m["mean_smooth"]) == len(m["rank"]) == n_years
    # The smoothed view starts once a full window of years exists.
    assert m["mean_smooth"][: m["window"] - 1] == [None] * (m["window"] - 1) and m["mean_smooth"][m["window"] - 1] is not None
    assert sorted(m["rank"]) == list(range(1, n_years + 1))
    assert m["mean"][m["rank"].index(1)] == max(m["mean"])
    assert client.get("/api/grid/years", params={"variable_id": "snow_depth"}).status_code == 400
    monkeypatch.setattr(main, "LAYERS_DIR", tmp_path)
    missing = client.get("/api/grid/years", params={"variable_id": "precip", "season": "JJA"})
    assert missing.status_code == 503 and missing.json()["error"]["code"] == "source_unavailable"


def test_grid_index_lists_built_layers(monkeypatch, tmp_path):
    from app import main
    index = client.get("/api/grid/index").json()
    assert len(index) == len(list(main.LAYERS_DIR.glob("trends_*.geojson")))
    assert {(x["variable_id"], x["season"]) for x in index} == {
        (v, s) for v in ("air_temp", "precip") for s in ("year", "JJA", "DJF")}
    djf = next(x for x in index if x["variable_id"] == "air_temp" and x["season"] == "DJF")
    assert djf == {"variable_id": "air_temp", "season": "DJF", "start_year": 1982, "end_year": 2025,
                   "units_per_decade": "°C/decade"}
    # Only what lies in the directory is listed.
    (tmp_path / "trends_PRECTOTCORR_JJA.geojson").write_bytes(
        (main.LAYERS_DIR / "trends_PRECTOTCORR_JJA.geojson").read_bytes())
    monkeypatch.setattr(main, "LAYERS_DIR", tmp_path)
    assert [(x["variable_id"], x["season"]) for x in client.get("/api/grid/index").json()] == [("precip", "JJA")]
    monkeypatch.setattr(main, "LAYERS_DIR", tmp_path / "missing")
    assert client.get("/api/grid/index").json() == []


def test_places_short_query_is_empty():
    assert client.get("/api/places", params={"q": "K"}).json() == []


def test_live_check_reuses_nearby_cmip6(fake_sources):
    r = client.post("/api/check", json=spec())
    sc = r.json()["scenarios"]
    assert sc is not None and sc["synthetic"] is False
    assert [p["id"] for p in sc["paths"]] == ["ssp126", "ssp245", "ssp585"]
    assert sc["baseline_value"] is not None
    for p in sc["paths"]:
        assert p["windows"][1] == "2041-2060"
        assert p["median_value"] == [round(sc["baseline_value"] + d, 2) for d in p["median"]]
        assert [a["year"] for a in p["analogs"]] == p["years"]
    assert any(p["source"] == "NASA NCCS" for p in r.json()["provenance"])


def test_no_scenarios_far_away_or_for_other_variables(fake_sources):
    far = dict(KYIV, place_id="x", name="Somewhere", lat=10.0, lon=10.0)
    assert client.post("/api/check", json=spec(place=far)).json()["scenarios"] is None
    assert client.post("/api/check", json=spec(variable_id="snow_depth", season="DJF")).json()["scenarios"] is None


def test_global_temp_uses_yearly_cag(monkeypatch):
    from app.sources import cag

    years = list(range(1850, 2026))
    rng = np.random.default_rng(3)
    anomaly = [round(0.008 * (y - 1850) - 0.3 + rng.normal(0, 0.1), 2) for y in years]
    seen = {}

    def fake(region, season):
        seen["args"] = (region, season)
        return {"years": years, "anomaly": anomaly, "base_period": "1901-2000", "units": "°C", "url": "https://cag.example"}

    monkeypatch.setattr(cag, "fetch_cag", fake)
    europe = {"place_id": "region:europe", "name": "Europe", "lat": 50.0, "lon": 15.0}
    r = client.post("/api/check", json=spec(variable_id="global_temp", place=europe, season="year",
                                            claim_text="Europe is getting warmer"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert seen["args"] == ("europe", "year")
    assert body["verdict"] == "confirmed" and body["witness"] is None and body["scenarios"] is None
    assert body["steps"][0]["title"] == "Yearly data" and len(body["series"]) == 45
    assert body["provenance"][0]["source"] == "NOAA Climate at a Glance"

    r2 = client.post("/api/check", json=spec(variable_id="global_temp", season="JJA"))   # a city -> the planet
    assert r2.status_code == 200 and seen["args"] == ("globe", "JJA")


def test_places_offers_regions(monkeypatch):
    from app.sources import geocode

    monkeypatch.setattr(geocode, "search_places", lambda q, **k: [])
    names = [p["place_id"] for p in client.get("/api/places", params={"q": "Euro"}).json()]
    assert names[0] == "region:europe"
    assert client.get("/api/places", params={"q": "world"}).json()[0]["place_id"] == "region:globe"
    assert client.get("/api/places", params={"q": "global"}).json()[0]["place_id"] == "region:globe"
    assert client.get("/api/places", params={"q": "Euro", "include_regions": "false"}).json() == []
    regions = client.get("/api/regions").json()
    assert [r["place_id"] for r in regions] == [f"region:{k}" for k in (
        "globe", "europe", "asia", "africa", "northamerica", "southamerica", "oceania", "arctic"
    )]


def test_region_file_gives_scenarios_for_any_cell(fake_sources, monkeypatch, tmp_path):
    import json as _json
    from app import scenarios as sc

    lats, lons = [44.125, 44.375, 44.625], [29.875, 30.125, 30.375]
    cube = lambda base: [[[round(base + h + 0.1 * i + 0.01 * j, 2) for j in range(3)] for i in range(3)]
                         for h in range(4)]
    block = {sid: {"median": cube(b), "low": cube(b - 0.5), "high": cube(b + 0.5)}
             for sid, b in (("ssp126", 1.0), ("ssp245", 1.5), ("ssp585", 2.0))}
    data = {"name": "t", "bbox": [44, 29.75, 44.75, 30.5], "grid": {"lat": lats, "lon": lons},
            "models": ["A", "B", "C"], "baseline_period": "1995-2014", "retrieved": "2026-11-15",
            "catalog_url": "https://example.test", "horizons": {"years": [2030, 2050, 2070, 2100], "windows": {"2030": "2021-2040", "2050": "2041-2060",
                                                                         "2070": "2061-2080", "2100": "2091-2100"}},
            "variables": {"tas": {"JJA": block}, "pr": {"JJA": block}}}
    (tmp_path / "region-t.json").write_text(_json.dumps(data))
    monkeypatch.setattr(sc, "CMIP6_DIR", tmp_path)
    sc._load.cache_clear()

    out = sc.nearby_scenarios("air_temp", "JJA", 44.4, 30.1)        # inside -> cell (1, 1)
    assert out["synthetic"] is False and out["source"].startswith("NASA NEX-GDDP-CMIP6 (3-model")
    assert out["paths"][0]["median"] == [1.11, 2.11, 3.11, 4.11]
    assert out["paths"][2]["high"][0] == 2.61
    assert out["paths"][0]["windows"] == ["2021-2040", "2041-2060", "2061-2080", "2091-2100"]
    assert sc.nearby_scenarios("air_temp", "JJA", 10.0, 10.0) is None
    assert sc.nearby_scenarios("snow_depth", "JJA", 44.4, 30.1) is None
    r = client.post("/api/check", json=spec(place={"place_id": "pt:44.40,30.10", "name": "Point", "lat": 44.4, "lon": 30.1}))
    assert r.status_code == 200, r.text
    assert r.json()["scenarios"]["paths"][0]["analogs"][0]["year"] == 2030
    sc._load.cache_clear()


def test_scenario_analogs_pick_closest_year_or_beyond_record():
    from app.scenarios import add_observed_context
    scen = {"baseline_value": 20.0, "paths": [{"years": [2050, 2100], "median": [1.4, 9.0],
                                               "low": [1.0, 5.0], "high": [2.0, 12.0]}]}
    out = add_observed_context(scen, [2000, 2001, 2002, 2003], [19.0, 21.5, None, 21.3], 2)
    p = out["paths"][0]
    assert p["median_value"] == [21.4, 29.0] and p["high_value"] == [22.0, 32.0]
    tie, far = p["analogs"]
    assert tie == {"year": 2050, "analog_year": 2003, "analog_value": 21.3, "analog_rank": 2, "beyond_record": False}
    assert far == {"year": 2100, "analog_year": None, "analog_value": None, "analog_rank": None, "beyond_record": True}


def test_steps_carry_structured_fields():
    import json
    from pathlib import Path
    r = json.loads((Path(__file__).resolve().parents[2] / "data/cases/kyiv-summer-heat.json").read_text())
    st = {s["id"]: s for s in r["steps"]}
    assert r["case"]["place"]["name"] == "Kyiv"
    assert st["raw"]["n_months"] == sum(m["value"] is not None for m in st["raw"]["monthly"]) == 540
    assert st["season"]["months"] == [6, 7, 8] and st["season"]["aggregation"] == "mean"
    assert st["season"]["years_dropped"] == [y["year"] for y in r["series"] if y["value"] is None]
    assert st["random_check"]["alpha"] == 0.05 and st["random_check"]["methods_agree"] is True
    assert st["random_check"]["fields"] == ["mk.p", "ols.p"]
    for s in r["steps"]:            # every path resolves in the result
        for path in s["fields"]:
            node = r
            for key in path.split("."):
                node = node[key]
