"""Unit and regression tests for trend estimation (backend/app/stats/trend.py)."""
import json
import math
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.stats.robustness import assess_robustness
from app.stats.seasonal import seasonal_series
from app.stats.trend import analyze_trend, mann_kendall, ols_effective, sen_slope

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_sen_recovers_known_slope_within_ci():
    rng = np.random.default_rng(1234)
    years = list(range(1981, 2026))
    true_slope = 0.06
    values = [15.0 + true_slope * (yr - 1981) + float(rng.normal(0.0, 0.5)) for yr in years]

    res = analyze_trend(years, values, start_year=1981)
    assert res is not None
    assert res.sen.ci_low_per_year <= true_slope <= res.sen.ci_high_per_year
    assert abs(res.sen.slope_per_year - true_slope) < 0.02
    assert abs(res.ols.slope_per_year - true_slope) < 0.02
    assert res.mk.p < 0.001
    assert res.mk.correction == "hamed_rao"
    assert res.mk.ess >= 1.0


def test_gaps_preserve_actual_year_slope_and_lag_acf():
    years = list(range(1981, 2026))
    true_slope = 0.25
    # Deterministic sawtooth residual: alternating +1, -1 on even vs odd years.
    # Dropping missing years must NOT turn a 2-year spacing into a lag-1 pair.
    values = [
        None if yr in (1981, 1990, 1991, 1992, 2005, 2015)
        else (10.0 + true_slope * (yr - 1981))
        for yr in years
    ]
    res = analyze_trend(years, values, start_year=1981)
    assert res is not None
    assert res.n == 39
    assert res.sen.slope_per_year == pytest.approx(true_slope, abs=1e-9)
    # Intercept is anchored at start_year=1981 even when 1981 itself is missing.
    assert res.sen.intercept_at_start == pytest.approx(10.0, abs=1e-9)
    assert res.ols.slope_per_year == pytest.approx(true_slope, abs=1e-9)

    # Check lag-1 respects calendar gaps: place +1/-1 pairs only across a missing gap,
    # while true consecutive pairs are uncorrelated / opposite.
    gap_years = [1, 2, 4, 5, 7, 8, 10, 11, 13, 14, 16, 17, 19, 20]
    # True lag-1 pairs (1-2, 4-5, ...) all have opposite signs (+1, -1), whereas
    # across each missing year (2->4, 5->7, ...) signs match (-1, -1) or (+1, +1) -> wait:
    # sequence of values: +1, -1,  -1, +1,  +1, -1, ...
    seq = [1.0, -1.0, -1.0, 1.0, 1.0, -1.0, -1.0, 1.0, 1.0, -1.0, -1.0, 1.0, 1.0, -1.0]
    ols = ols_effective(gap_years, seq)
    # Consecutive lag-1 products are negative, so r1 < 0 and phi must stay 0.0, n_eff == n.
    assert ols.phi == 0.0
    assert ols.n_eff == pytest.approx(float(len(gap_years)))


def test_kharkiv_jja_precip_regression_no_nan():
    # Keep the regression reproducible in a clean checkout, without a local data cache.
    kharkiv = json.loads((FIXTURES / "kharkiv-precip-monthly.json").read_text(encoding="utf-8"))
    years, vals = seasonal_series(
        kharkiv["power"]["series"]["PRECTOTCORR"], "JJA", "sum", 1981, 2025, per_day=True
    )
    main = analyze_trend(years, vals, start_year=1981)
    assert main is not None
    assert math.isfinite(main.mk.p) and 0.0 <= main.mk.p <= 1.0
    assert math.isfinite(main.mk.z)
    assert main.mk.ess >= 1.0

    # Shifted robustness windows
    rob = assess_robustness(years, vals, main.sen.slope_per_year, 1981, 2025)
    assert rob.total == 5
    for w in rob.windows:
        assert math.isfinite(w.p) and 0.0 <= w.p <= 1.0
        assert math.isfinite(w.slope_per_decade)

    # Specifically sweep all >=15-year contiguous sub-windows (reproduces 1984-2022 negative var bug)
    for i in range(len(years)):
        for j in range(i + 15, len(years) + 1):
            sub_res = analyze_trend(years[i:j], vals[i:j])
            assert sub_res is not None
            assert math.isfinite(sub_res.mk.p) and 0.0 <= sub_res.mk.p <= 1.0
            assert math.isfinite(sub_res.mk.z)
            assert math.isfinite(sub_res.mk.tau)
            assert sub_res.mk.ess >= 1.0


def test_constant_and_tied_series_edge_cases():
    years = list(range(1981, 2001))
    const = [5.0] * len(years)
    res = analyze_trend(years, const)
    assert res is not None
    assert res.sen.slope_per_year == 0.0
    assert res.mk.p == 1.0
    assert res.mk.z == 0.0
    assert res.ols.p == 1.0

    tied = [1.0, 1.0, 2.0, 2.0, 3.0, 3.0, 4.0, 4.0, 5.0, 5.0, 6.0, 6.0, 7.0, 7.0, 8.0]
    mk = mann_kendall(years[: len(tied)], tied)
    assert mk.p < 0.001
    assert mk.tau > 0.8

    s = sen_slope(years[:4], [1.0, 2.0, 3.0, 4.0])
    assert s.slope_per_year == pytest.approx(1.0)


def test_ols_effective_reduces_n_eff_on_ar1_residuals():
    rng = np.random.default_rng(7)
    n = 60
    years = list(range(1966, 1966 + n))
    err = np.empty(n)
    err[0] = rng.normal()
    for t in range(1, n):
        err[t] = 0.65 * err[t - 1] + rng.normal(0.0, math.sqrt(1.0 - 0.65**2))

    ols = ols_effective(years, err.tolist())
    assert ols.phi > 0.3
    assert 3.0 <= ols.n_eff < n
