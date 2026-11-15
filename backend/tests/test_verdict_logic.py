"""Verdict rules for short periods, empty and constant series, and request hardening."""
from pathlib import Path
import sys

import numpy as np
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import check as check_mod
from app.check import MainSeries, station_name
from app.main import app
from app.stats.history import detection_history
from app.stats.robustness import assess_robustness, required_windows
from app.verdict import evaluate_verdict

client = TestClient(app)
KYIV = {"place_id": "om:703448", "name": "Kyiv, Ukraine", "lat": 50.45, "lon": 30.52}


def spec(**over):
    s = {"claim_text": "Summers in Kyiv are getting hotter", "variable_id": "air_temp", "place": KYIV,
         "season": "JJA", "start_year": 1981, "end_year": 2025, "claim_direction": "increase"}
    s.update(over)
    return s


def trend_series(n, slope=0.5, sd=0.3, seed=3):
    rng = np.random.default_rng(seed)
    years = list(range(2025 - n + 1, 2026))
    return years, list(slope * np.arange(n) + rng.normal(0, sd, n))


def test_required_windows_table():
    assert [required_windows(t) for t in range(6)] == [0, 1, 2, 3, 4, 4]


@pytest.mark.parametrize("n", [15, 18, 20, 21])
def test_strong_trend_on_short_periods_is_confirmed(n):
    years, vals = trend_series(n)
    ev = evaluate_verdict(years, vals, direction="increase", compute_wait=False)
    assert (ev.verdict, ev.reason) == ("confirmed", "significant_trend")
    assert ev.robustness.total == {15: 1, 18: 3, 20: 3, 21: 5}[n]


def test_trend_in_one_of_three_windows_is_not_robust():
    # 20 years: flat for 11, then a ramp. Only the full period is significant; both shifted
    # windows (start +3, end −3) are not.
    rng = np.random.default_rng(5)
    t = np.arange(20)
    vals = list(np.where(t >= 11, (t - 10) * 0.35, 0.0) + rng.normal(0, 0.25, 20))
    ev = evaluate_verdict(list(range(2006, 2026)), vals, direction="increase", compute_wait=False)
    assert ev.main.mk.p < 0.05
    assert (ev.robustness.significant, ev.robustness.total) == (1, 3)
    assert (ev.verdict, ev.reason) == ("not_proven", "not_robust")


def test_windows_with_gaps_do_not_vote():
    years, vals = trend_series(21)
    vals[3:9] = [None] * 6      # windows starting 3 or 6 years later keep < 15 values
    rob = assess_robustness(years, vals, 0.5, years[0], years[-1])
    assert all(w.n >= 15 for w in rob.windows)
    assert rob.total < 5


def test_short_series_skips_robustness():
    years, vals = trend_series(12)
    ev = evaluate_verdict(years, vals, direction="increase", compute_wait=False)
    assert (ev.verdict, ev.reason) == ("not_proven", "short_series")
    assert ev.robustness.total == 0


def test_constant_series_is_no_variation():
    years = list(range(1981, 2026))
    ev = evaluate_verdict(years, [0.0] * len(years), direction="increase")
    assert (ev.verdict, ev.reason) == ("not_proven", "no_variation")
    assert ev.years_to_wait is None


def test_emerged_year():
    years, vals = trend_series(30, slope=0.3, sd=0.5)
    h = detection_history(years, vals, alpha=0.05, min_observations=15)
    assert h["emerged_year"] is not None
    tail = [p for p in h["points"] if p["end_year"] >= h["emerged_year"]]
    assert all(p["p"] < 0.05 for p in tail)
    before = [p for p in h["points"] if p["end_year"] == h["emerged_year"] - 1]
    assert not before or before[0]["p"] is None or before[0]["p"] >= 0.05

    noise = list(np.random.default_rng(5).normal(0, 1, 30))
    assert detection_history(years, noise, alpha=0.05, min_observations=15)["emerged_year"] is None


def test_station_renames():
    assert station_name("DNIPROPETROVSK, UP") == "Dnipro"
    assert station_name("ZAPOROZHYE, UP") == "Zaporizhzhia"


# ---------- API ----------

def _fake_main(values):
    def main_series(var, lat, lon, start, end):
        return MainSeries(monthly=values, start="1980-01", url="https://power.example/test",
                          retrieved_at="2026-11-14T00:00:00Z")
    return main_series


def test_point_without_data_is_400_no_data(monkeypatch):
    monkeypatch.setattr(check_mod, "fetch_main_series", _fake_main([None] * (46 * 12)))
    monkeypatch.setattr(check_mod, "fetch_station", lambda *a: None)
    r = client.post("/api/check", json=spec(variable_id="soil_moisture"))
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "no_data"
    assert "open ocean" in r.json()["error"]["message"]


def test_low_coverage_warning(monkeypatch):
    vals = [10.0 + 0.1 * (i // 12) + (i % 7) * 0.01 for i in range(46 * 12)]
    for y in range(1981, 2006):          # 25 of 45 summers missing → 20 valid years
        vals[(y - 1980) * 12 + 6] = None
    monkeypatch.setattr(check_mod, "fetch_main_series", _fake_main(vals))
    monkeypatch.setattr(check_mod, "fetch_station", lambda *a: None)
    r = client.post("/api/check", json=spec())
    assert r.status_code == 200, r.text
    yearly = next(s for s in r.json()["steps"] if s["id"] == "yearly")
    assert "Data cover only 20 of 45 years" in yearly["detail"]


def test_unhandled_error_is_json_internal(monkeypatch):
    def boom(spec):
        raise KeyError("unexpected")
    monkeypatch.setattr("app.main.run_check", boom)
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post("/api/check", json=spec())
    assert r.status_code == 500
    assert r.json() == {"error": {"code": "internal",
                                  "message": "Something went wrong on our side. Try again or open a saved case."}}


@pytest.mark.parametrize("over", [
    {"season": True}, {"season": "7"}, {"start_year": "1981"}, {"start_year": 1981.0},
    {"claim_text": "x" * 301}, {"place": {**KYIV, "name": "x" * 201}},
])
def test_strict_spec_fields(over):
    r = client.post("/api/check", json=spec(**over))
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "bad_request"


def test_body_over_limit_is_413():
    big = b'{"claim_text": "' + b"x" * (300 * 1024) + b'"}'
    r = client.post("/api/check", content=big, headers={"content-type": "application/json"})
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "bad_request"


def test_chunked_body_over_limit_is_413():
    def chunks():
        yield b'{"claim_text": "'
        for _ in range(300):
            yield b"x" * 1024
        yield b'"}'
    r = client.post("/api/chat", content=chunks(), headers={"content-type": "application/json"})
    assert r.status_code == 413
