"""Trend band and baseline mean (chart geometry)."""
from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.stats.band import baseline_mean, sen_band
from app.stats.trend import sen_slope


def _band(years, vals, start, end):
    s = sen_slope(years, vals, start_year=start)
    return s, sen_band([y for y, v in zip(years, vals) if v is not None], slope_per_year=s.slope_per_year,
                       ci_low_per_year=s.ci_low_per_year, ci_high_per_year=s.ci_high_per_year,
                       intercept_at_start=s.intercept_at_start, start_year=start, end_year=end, decimals=2)


def test_band_is_a_fan_around_the_sen_line():
    rng = np.random.default_rng(3)
    years = list(range(1981, 2026))
    vals = [10 + 0.04 * (y - 1981) + float(rng.normal(0, 0.5)) for y in years]
    s, (py, pv, band) = _band(years, vals, 1981, 2025)

    assert py == 2003.0 and len(band) == 45 and [b["year"] for b in band] == years
    at = {b["year"]: b for b in band}
    assert at[2003]["low"] == at[2003]["mid"] == at[2003]["high"] == pytest.approx(pv, abs=0.01)
    assert pv == pytest.approx(s.intercept_at_start + s.slope_per_year * (2003 - 1981), abs=0.01)
    for b in band:
        assert b["low"] <= b["mid"] <= b["high"]
        assert b["mid"] == pytest.approx(s.intercept_at_start + s.slope_per_year * (b["year"] - 1981), abs=0.01)
    # narrowest at the pivot, widest at the ends
    width = [b["high"] - b["low"] for b in band]
    assert min(width) == pytest.approx(width[22], abs=0.011) and width[0] > width[10] > width[22]
    # the ends of the band match the slope interval
    assert at[2025]["high"] - at[2025]["mid"] == pytest.approx(
        (s.ci_high_per_year - s.slope_per_year) * (2025 - 2003), abs=0.02)


def test_band_with_gaps_uses_only_years_with_data():
    years = list(range(2000, 2021))
    vals = [None if 2006 <= y <= 2013 else 5 + 0.1 * (y - 2000) for y in years]
    _, (py, _, band) = _band(years, vals, 2000, 2020)
    assert py == 2014.0 and len(band) == 21          # gap years still get a band, so the chart has no hole


def test_baseline_uses_normal_when_covered_else_series_mean():
    years = list(range(1981, 2026))
    vals = [float(y - 1981) for y in years]
    b = baseline_mean(years, vals, 2)
    assert b["kind"] == "normal_1991_2020" and b["period"] == "1991-2020" and b["n_years"] == 30
    assert b["mean"] == pytest.approx(24.5)

    short = baseline_mean(list(range(2000, 2026)), [1.0] * 26, 2)      # 21 years in 1991-2020 < 24
    assert short["kind"] == "series_mean" and short["period"] == "2000-2025" and short["mean"] == 1.0

    gappy = [None if 1995 <= y <= 2002 else 1.0 for y in years]         # 22 valid years in 1991-2020
    assert baseline_mean(years, gappy, 2)["kind"] == "series_mean"
