"""Offline tests for backend/app/sources adapters."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import sys
import urllib.error
import urllib.parse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.sources import (  # noqa: E402
    CAG_REGIONS,
    CAG_SEASONS,
    GIOVANNI_VARS,
    PowerMonthly,
    SourceUnavailable,
    StationSeries,
    best_station,
    cache,
    cag,
    fetch_cag,
    fetch_giovanni_monthly,
    fetch_power_monthly,
    geocode,
    giovanni,
    noaa,
    power,
    search_places,
    source_name,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sources"


def _seed_cache(tmp_path: Path, url: str, params: dict | None, content: str, ext: str = "json") -> Path:
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    key = hashlib.sha1(full.encode()).hexdigest()[:16]
    cdir = tmp_path / "cache"
    cdir.mkdir(parents=True, exist_ok=True)
    target = cdir / f"{key}.{ext}"
    target.write_text(content, encoding="utf-8")
    return target


@pytest.fixture
def offline_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("EV_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OFFLINE", "1")
    return tmp_path


class _FakeResponse:
    def __init__(self, body: str) -> None:
        self._data = body.encode("utf-8")

    def read(self) -> bytes:
        return self._data

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_source_name_derivation():
    assert source_name("https://power.larc.nasa.gov/api/temporal/monthly/point") == "power"
    assert source_name("https://www.ncei.noaa.gov/access/services/data/v1") == "noaa"
    assert source_name("https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/global/time-series/globe/land_ocean/3/8/1850-2026/data.json") == "cag"
    assert source_name("https://api.giovanni.earthdata.nasa.gov/timeseries") == "giovanni"
    assert source_name("https://geocoding-api.open-meteo.com/v1/search") == "open-meteo"


def test_offline_miss_raises_source_unavailable(offline_cache: Path, monkeypatch: pytest.MonkeyPatch):
    def boom(*args, **kwargs):
        raise AssertionError("network must not be called when OFFLINE=1")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(SourceUnavailable) as exc_info:
        cache.get_json("https://power.larc.nasa.gov/api/temporal/monthly/point", {"foo": "bar"})
    assert exc_info.value.source == "power"
    assert "offline" in exc_info.value.message.lower()


def test_4xx_fails_fast_without_retries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EV_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OFFLINE", raising=False)
    calls = 0

    def fake_urlopen(req, timeout=120):
        nonlocal calls
        calls += 1
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(b"missing"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("time.sleep", lambda _: None)

    with pytest.raises(SourceUnavailable) as exc_info:
        cache.get_json("https://www.ncei.noaa.gov/access/services/data/v1", {"x": 1})
    assert exc_info.value.source == "noaa"
    assert calls == 1


def test_5xx_and_429_retry_with_backoff(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EV_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OFFLINE", raising=False)
    calls = 0
    sleeps: list[float] = []

    def fake_urlopen(req, timeout=120):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise urllib.error.HTTPError(req.full_url, 503, "Service Unavailable", {}, io.BytesIO(b""))
        if calls == 2:
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, io.BytesIO(b""))
        return _FakeResponse('{"ok": true}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("time.sleep", sleeps.append)

    res = cache.get_json("https://power.larc.nasa.gov/api/test", {"a": 1}, headers={"Authorization": "Bearer TOPSECRET"})
    assert res == {"ok": True}
    assert calls == 3
    assert len(sleeps) == 2

    # Cache file key ignores headers and contains only response body.
    cfiles = list((tmp_path / "cache").glob("*.json"))
    assert len(cfiles) == 1
    assert "TOPSECRET" not in cfiles[0].read_text()


def test_power_parsing_drops_month_13_and_maps_missing_to_none(offline_cache: Path):
    raw = (FIXTURES / "power_kyiv_1981_1983.json").read_text(encoding="utf-8")
    params = {
        "parameters": "T2M,ALLSKY_SFC_SW_DWN",
        "community": "AG",
        "latitude": 50.45,
        "longitude": 30.52,
        "start": 1981,
        "end": 1983,
        "format": "JSON",
    }
    _seed_cache(offline_cache, power.POWER_URL, params, raw, ext="json")

    res = fetch_power_monthly(50.45, 30.52, ["T2M", "ALLSKY_SFC_SW_DWN"], 1981, 1983)
    assert isinstance(res, PowerMonthly)
    assert res.start == "1981-01"
    assert len(res.series["T2M"]) == 36
    assert len(res.series["ALLSKY_SFC_SW_DWN"]) == 36
    assert all(v is not None for v in res.series["T2M"])
    assert all(v is None for v in res.series["ALLSKY_SFC_SW_DWN"])
    assert res.units == {"T2M": "C", "ALLSKY_SFC_SW_DWN": "MJ/m^2/day"}
    assert res.grid_cell == (30.52, 50.45)


def test_power_caps_end_year_and_rounds_coords(offline_cache: Path):
    raw = json.loads((FIXTURES / "power_kyiv_1981_1983.json").read_text(encoding="utf-8"))
    # Extend raw fixture in-memory to cover 1981..2025 for T2M.
    t2m = raw["properties"]["parameter"]["T2M"]
    for y in range(1984, 2026):
        for m in range(1, 13):
            t2m[f"{y}{m:02d}"] = 10.0
        t2m[f"{y}13"] = 10.0

    expected_params = {
        "parameters": "T2M",
        "community": "AG",
        "latitude": 50.4512,
        "longitude": 30.5246,
        "start": 1981,
        "end": 2025,
        "format": "JSON",
    }
    _seed_cache(offline_cache, power.POWER_URL, expected_params, json.dumps(raw), ext="json")

    res = power.fetch_monthly(50.451234, 30.524567, ["T2M"], 1981, 2026)
    assert len(res.series["T2M"]) == (2025 - 1981 + 1) * 12
    assert "end=2025" in res.url
    assert "latitude=50.4512" in res.url
    assert "longitude=30.5246" in res.url


def test_noaa_daily_fallback_on_real_fixture(offline_cache: Path):
    _seed_cache(
        offline_cache,
        noaa.SEARCH_URL,
        {
            "dataset": "global-summary-of-the-month",
            "bbox": "51.15,29.52,49.75,31.52",
            "startDate": "2022-01-01",
            "endDate": "2023-12-31",
            "limit": 20,
        },
        (FIXTURES / "noaa_search_kyiv_2022_2023.json").read_text(encoding="utf-8"),
    )
    _seed_cache(
        offline_cache,
        noaa.DATA_URL,
        {
            "dataset": "global-summary-of-the-month",
            "stations": "UPM00033345",
            "startDate": "2022-01-01",
            "endDate": "2023-12-31",
            "dataTypes": "TAVG",
            "format": "json",
            "units": "metric",
        },
        (FIXTURES / "noaa_gsom_kyiv_2022_2023.json").read_text(encoding="utf-8"),
    )
    for y in (2022, 2023):
        _seed_cache(
            offline_cache,
            noaa.DATA_URL,
            {
                "dataset": "daily-summaries",
                "stations": "UPM00033345",
                "startDate": f"{y}-01-01",
                "endDate": f"{y}-12-31",
                "dataTypes": "TAVG",
                "format": "json",
                "units": "metric",
            },
            (FIXTURES / f"noaa_daily_kyiv_{y}.json").read_text(encoding="utf-8"),
        )

    stn = best_station(50.45, 30.52, "TAVG", 2022, 2023, candidates=1)
    assert isinstance(stn, StationSeries)
    assert stn.id == "UPM00033345"
    assert stn.name == "KIEV, UP"
    assert stn.method == "ghcnd-daily-mean"
    assert len(stn.monthly) == 24
    assert stn.coverage == pytest.approx(21 / 24, abs=1e-4)
    assert stn.monthly[0] == -1.37


def test_noaa_gsom_used_when_coverage_sufficient_and_never_spliced(offline_cache: Path):
    search_payload = {
        "results": [
            {
                "stations": [{"id": "TEST001", "name": "TEST STATION"}],
                "boundingPoints": [{"coordinates": [30.5, 50.45]}],
            }
        ]
    }
    _seed_cache(
        offline_cache,
        noaa.SEARCH_URL,
        {
            "dataset": "global-summary-of-the-month",
            "bbox": "51.15,29.52,49.75,31.52",
            "startDate": "2022-01-01",
            "endDate": "2023-12-31",
            "limit": 20,
        },
        json.dumps(search_payload),
    )
    # 22 of 24 months (91.7% >= 90%) -> no daily request should be attempted.
    gsom_rows = [{"DATE": f"2022-{m:02d}", "TAVG": "10.0"} for m in range(1, 13)]
    gsom_rows += [{"DATE": f"2023-{m:02d}", "TAVG": "11.0"} for m in range(1, 11)]
    _seed_cache(
        offline_cache,
        noaa.DATA_URL,
        {
            "dataset": "global-summary-of-the-month",
            "stations": "TEST001",
            "startDate": "2022-01-01",
            "endDate": "2023-12-31",
            "dataTypes": "TAVG",
            "format": "json",
            "units": "metric",
        },
        json.dumps(gsom_rows),
    )

    stn = best_station(50.45, 30.52, "TAVG", 2022, 2023)
    assert stn is not None
    assert stn.method == "gsom"
    assert stn.monthly[-2:] == [None, None]

    # Now test GSOM < 90% (18/24) when daily has fewer months (10/24): must keep pure GSOM.
    _seed_cache(
        offline_cache,
        noaa.DATA_URL,
        {
            "dataset": "global-summary-of-the-month",
            "stations": "TEST001",
            "startDate": "2022-01-01",
            "endDate": "2023-12-31",
            "dataTypes": "TAVG",
            "format": "json",
            "units": "metric",
        },
        json.dumps(gsom_rows[:18]),
    )
    daily_2022 = [{"DATE": f"2022-01-{d:02d}", "TAVG": "1.0"} for d in range(1, 26)]
    _seed_cache(
        offline_cache,
        noaa.DATA_URL,
        {
            "dataset": "daily-summaries",
            "stations": "TEST001",
            "startDate": "2022-01-01",
            "endDate": "2022-12-31",
            "dataTypes": "TAVG",
            "format": "json",
            "units": "metric",
        },
        json.dumps(daily_2022),
    )
    _seed_cache(
        offline_cache,
        noaa.DATA_URL,
        {
            "dataset": "daily-summaries",
            "stations": "TEST001",
            "startDate": "2023-01-01",
            "endDate": "2023-12-31",
            "dataTypes": "TAVG",
            "format": "json",
            "units": "metric",
        },
        json.dumps([]),
    )
    stn2 = best_station(50.45, 30.52, "TAVG", 2022, 2023)
    assert stn2 is not None
    assert stn2.method == "gsom"
    assert sum(v is not None for v in stn2.monthly) == 18


def test_noaa_prcp_requires_every_day_of_month(offline_cache: Path):
    search_payload = {
        "results": [
            {
                "stations": [{"id": "PRCP001", "name": "RAIN STN"}],
                "boundingPoints": [{"coordinates": [30.5, 50.45]}],
            }
        ]
    }
    _seed_cache(
        offline_cache,
        noaa.SEARCH_URL,
        {
            "dataset": "global-summary-of-the-month",
            "bbox": "51.15,29.52,49.75,31.52",
            "startDate": "2024-01-01",
            "endDate": "2024-12-31",
            "limit": 20,
        },
        json.dumps(search_payload),
    )
    _seed_cache(
        offline_cache,
        noaa.DATA_URL,
        {
            "dataset": "global-summary-of-the-month",
            "stations": "PRCP001",
            "startDate": "2024-01-01",
            "endDate": "2024-12-31",
            "dataTypes": "PRCP",
            "format": "json",
            "units": "metric",
        },
        json.dumps([]),
    )
    # 2024 is a leap year: Jan has 31/31 days (valid), Feb has 28/29 days (invalid -> None), Mar has 31/31.
    daily_2024 = (
        [{"DATE": f"2024-01-{d:02d}", "PRCP": "1.5"} for d in range(1, 32)]
        + [{"DATE": f"2024-02-{d:02d}", "PRCP": "2.0"} for d in range(1, 29)]
        + [{"DATE": f"2024-03-{d:02d}", "PRCP": "1.0"} for d in range(1, 32)]
    )
    _seed_cache(
        offline_cache,
        noaa.DATA_URL,
        {
            "dataset": "daily-summaries",
            "stations": "PRCP001",
            "startDate": "2024-01-01",
            "endDate": "2024-12-31",
            "dataTypes": "PRCP",
            "format": "json",
            "units": "metric",
        },
        json.dumps(daily_2024),
    )

    stn = best_station(50.45, 30.52, "PRCP", 2024, 2024)
    assert stn is not None
    assert stn.method == "ghcnd-daily-sum"
    assert stn.monthly[0] == 46.5
    assert stn.monthly[1] is None
    assert stn.monthly[2] == 31.0


def test_noaa_no_station_within_max_km_returns_none(offline_cache: Path):
    _seed_cache(
        offline_cache,
        noaa.SEARCH_URL,
        {
            "dataset": "global-summary-of-the-month",
            "bbox": "51.15,29.52,49.75,31.52",
            "startDate": "2022-01-01",
            "endDate": "2023-12-31",
            "limit": 20,
        },
        (FIXTURES / "noaa_search_kyiv_2022_2023.json").read_text(encoding="utf-8"),
    )
    assert best_station(50.45, 30.52, "TAVG", 2022, 2023, max_km=0.1) is None


def test_geocode_empty_query():
    assert search_places("") == []
    assert search_places("   \t ") == []


def test_geocode_ranking_capital_and_admin_first(offline_cache: Path):
    synthetic_kiev = {
        "results": [
            {
                "id": 827619,
                "name": "Kiev",
                "latitude": 59.0,
                "longitude": 54.0,
                "country_code": "RU",
                "country": "Russia",
                "admin1": "Perm Krai",
                "population": 1,
                "feature_code": "PPL",
            },
            {
                "id": 999999,
                "name": "Kievka",
                "latitude": 51.0,
                "longitude": 40.0,
                "country_code": "RU",
                "country": "Russia",
                "admin1": "Rostov",
                "population": 500000,
                "feature_code": "PPL",
            },
            {
                "id": 703448,
                "name": "Kyiv",
                "latitude": 50.45466,
                "longitude": 30.5238,
                "country_code": "UA",
                "country": "Ukraine",
                "admin1": "Kyiv City",
                "population": 2952301,
                "feature_code": "PPLC",
            },
        ]
    }
    _seed_cache(
        offline_cache,
        geocode.GEOCODE_URL,
        {"name": "Kiev", "count": 10, "language": "en", "format": "json"},
        json.dumps(synthetic_kiev),
    )

    places = search_places("Kiev", count=2)
    assert len(places) == 2
    assert places[0] == {
        "place_id": "om:703448",
        "name": "Kyiv, Ukraine",
        "lat": 50.45466,
        "lon": 30.5238,
        "country_code": "UA",
        "admin1": "Kyiv City",
        "population": 2952301,
        "feature_code": "PPLC",
    }
    assert places[1]["place_id"] == "om:999999"


def test_geocode_real_fixtures_and_cyrillic_merge(offline_cache: Path):
    _seed_cache(
        offline_cache,
        geocode.GEOCODE_URL,
        {"name": "Kiev", "count": 10, "language": "en", "format": "json"},
        (FIXTURES / "geocode_kiev_en.json").read_text(encoding="utf-8"),
    )
    _seed_cache(
        offline_cache,
        geocode.GEOCODE_URL,
        {"name": "Kyiv", "count": 10, "language": "en", "format": "json"},
        (FIXTURES / "geocode_kyiv_en.json").read_text(encoding="utf-8"),
    )
    _seed_cache(
        offline_cache,
        geocode.GEOCODE_URL,
        {"name": "Київ", "count": 10, "language": "en", "format": "json"},
        (FIXTURES / "geocode_kyiv_uk_query_en.json").read_text(encoding="utf-8"),
    )
    _seed_cache(
        offline_cache,
        geocode.GEOCODE_URL,
        {"name": "Київ", "count": 10, "language": "uk", "format": "json"},
        (FIXTURES / "geocode_kyiv_uk_query_uk.json").read_text(encoding="utf-8"),
    )

    assert search_places("Kyiv")[0]["name"] == "Kyiv, Ukraine"
    assert search_places("Kiev")[0]["name"] == "Kyiv, Ukraine"
    uk_res = search_places("Київ")
    assert uk_res[0]["place_id"] == "om:703448"
    assert uk_res[0]["name"] == "Київ, Україна"


def test_cag_real_fixture_and_seasons(offline_cache: Path):
    url = f"{cag.CAG_BASE_URL}/globe/land_ocean/3/8/1850-2026/data.json"
    _seed_cache(
        offline_cache,
        url,
        None,
        (FIXTURES / "cag_globe_jja.json").read_text(encoding="utf-8"),
    )
    res = fetch_cag("globe", "JJA")
    assert res["base_period"] == "1901-2000"
    assert res["units"] == "°C"
    assert res["url"] == url
    assert res["years"][0] == 1850
    assert len(res["years"]) == len(res["anomaly"])
    assert set(CAG_SEASONS) == {"year", "djf", "mam", "jja", "son"}
    assert "europe" in CAG_REGIONS

    with pytest.raises(ValueError):
        fetch_cag("atlantis", "JJA")
    with pytest.raises(ValueError):
        fetch_cag("globe", "XYZ")


def test_giovanni_missing_token_and_csv_parsing(offline_cache: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)
    monkeypatch.setenv("HOME", str(offline_cache))
    with pytest.raises(SourceUnavailable) as exc_info:
        fetch_giovanni_monthly("precip_gpm", 50.45, 30.52, 2022, 2023)
    assert exc_info.value.source == "giovanni"

    monkeypatch.setenv("EARTHDATA_TOKEN", "secret-token-value")
    endpoint = f"{giovanni.GIOVANNI_URL}/timeseries"
    params = {
        "data": GIOVANNI_VARS["precip_gpm"][0],
        "location": "[50.45,30.52]",
        "time": "2022-01-01T00:00:00/2023-12-31T23:59:59",
    }
    _seed_cache(
        offline_cache,
        endpoint,
        params,
        (FIXTURES / "giovanni_precip_2022_2023.csv").read_text(encoding="utf-8"),
        ext="csv",
    )

    res = fetch_giovanni_monthly("precip_gpm", 50.45, 30.52, 2022, 2023)
    assert res["variable"] == "GPM_3IMERGM_07_precipitation"
    assert res["units"] == "mm/day"
    assert res["source_units"] == "mm/hr"
    assert res["start"] == "2022-01"
    assert len(res["monthly"]) == 24
    assert res["monthly"][0] == pytest.approx(1.968)
    assert "secret-token-value" not in res["url"]
