"""Sen interval with the MK autocorrelation inflation, full-record scenario baseline, BACI climatology."""
from pathlib import Path
import sys

import numpy as np
import pytest
from scipy.stats import theilslopes

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.catalog import get_variable  # noqa: E402
from app.check import MainSeries, assemble_result  # noqa: E402
from app.models import CaseSpec  # noqa: E402
from app.stats.event import _evaluate_baci_window, _outside_climatology  # noqa: E402
from app.stats.trend import analyze_trend, sen_slope  # noqa: E402


def ar1(rng, n, phi):
    e = np.empty(n)
    e[0] = rng.normal()
    for k in range(1, n):
        e[k] = phi * e[k - 1] + rng.normal() * np.sqrt(1 - phi ** 2)
    return e


def test_sen_interval_with_ess_one_equals_theilslopes():
    rng = np.random.default_rng(0)
    for _ in range(200):
        n = int(rng.integers(5, 60))
        x = np.arange(n) + 1981.0
        y = np.round(rng.normal(0, 1, n) + 0.02 * np.arange(n), 1)    # rounding gives ties
        ours, ref = sen_slope(x, y, ess=1.0), theilslopes(y, x, alpha=0.95)
        assert ours.slope_per_year == pytest.approx(ref.slope, abs=1e-12)
        assert ours.ci_low_per_year == pytest.approx(ref.low_slope, abs=1e-12)
        assert ours.ci_high_per_year == pytest.approx(ref.high_slope, abs=1e-12)
        assert ours.intercept_at_start == pytest.approx(ref.intercept + ref.slope * 1981, abs=1e-9)


def test_autocorrelated_series_gets_a_wider_interval():
    rng = np.random.default_rng(1)
    years = list(range(1981, 2026))
    y = list(0.03 * np.arange(45) + ar1(rng, 45, 0.5))
    tr = analyze_trend(years, y)
    plain = sen_slope(years, y, ess=1.0)
    assert tr.mk.ess > 1
    assert tr.sen.ci_high_per_year - tr.sen.ci_low_per_year > plain.ci_high_per_year - plain.ci_low_per_year


def test_interval_and_p_agree():
    rng = np.random.default_rng(2)
    years = list(range(1981, 2026))
    disagree = 0
    n = 2000
    for _ in range(n):
        slope, phi = rng.choice([0.0, 0.02, 0.04]), rng.choice([0.0, 0.3, 0.5])
        tr = analyze_trend(years, list(slope * np.arange(45) + ar1(rng, 45, phi)))
        excludes_zero = tr.sen.ci_low_per_year > 0 or tr.sen.ci_high_per_year < 0
        disagree += excludes_zero != (tr.mk.p < 0.05)
    assert disagree / n < 0.02


# ---------- scenario baseline from the full record ----------

def _scenarios():
    path = dict(id="ssp245", label="Middle road", years=[2050], windows=["2041-2060"],
                median=[1.0], low=[0.5], high=[1.5])
    return dict(synthetic=True, source="test", baseline_period="1995-2014", note="Not a forecast",
                paths=[path], provenance=[])


def _result(start_year, monthly=None):
    var = get_variable("air_temp")
    if monthly is None:
        monthly = [15.0 + 0.03 * (i // 12) + (i % 5) * 0.1 for i in range(45 * 12)]
    spec = CaseSpec(claim_text="t", variable_id="air_temp",
                    place=dict(place_id="t", name="T", lat=50.0, lon=30.0),
                    season="JJA", start_year=start_year, end_year=2025, claim_direction="increase")
    ms = MainSeries(monthly=monthly, start="1981-01", url="https://power.example", retrieved_at="2026-01-01T00:00:00Z")
    return assemble_result(spec, var, ms, scenarios=_scenarios())


def test_baseline_comes_from_full_record_not_case_period():
    r_full, r_late = _result(1981), _result(2005)
    assert r_late.scenarios is not None
    assert r_late.scenarios.baseline_n_years == 20
    assert r_late.scenarios.baseline_value == r_full.scenarios.baseline_value
    assert r_late.case.start_year == 2005 and r_late.series[0].year == 2005


def test_no_scenarios_without_15_baseline_years():
    monthly = [15.0 + 0.03 * (i // 12) + (i % 5) * 0.1 for i in range(45 * 12)]
    for y in range(1995, 2001):                       # 6 of 20 baseline summers missing
        monthly[(y - 1981) * 12 + 6] = None
    r = _result(1981, monthly)
    assert r.scenarios is None
    assert all(p.what != "Future scenarios" for p in r.provenance)


# ---------- BACI with a one-year window ----------

def test_one_year_window_keeps_before_variance():
    rng = np.random.default_rng(3)
    n = 20 * 12
    site = 10 + 3 * np.sin(2 * np.pi * np.arange(n) / 12) + rng.normal(0, 1, n)
    clim = _outside_climatology(site, 108, 132)
    before = site[108:120] - clim
    # A climatology from the "before" window alone made these anomalies exactly zero.
    assert np.var(before, ddof=1) > 0.3
    ev = _evaluate_baci_window(site, None, 120, 12, min_coverage=0.6, compute_bootstrap=False,
                               block_size=3, n_bootstrap=0, bootstrap_seed=0)
    assert ev is not None and 0.0 < ev.p < 1.0
