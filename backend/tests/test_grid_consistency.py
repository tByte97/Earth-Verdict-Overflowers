"""The globe layer and a point check use the same seasonal aggregation and the same trend test."""
from pathlib import Path
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))
import build_grid_trends as grid  # noqa: E402
from app.stats import seasonal_series  # noqa: E402
from app.stats.trend import analyze_trend  # noqa: E402


def cell_monthly(seed: int) -> list[float]:
    rng = np.random.default_rng(seed)
    n = (grid.END - grid.START + 1) * 12
    t = np.arange(n)
    return list(10 - 8 * np.cos(2 * np.pi * t / 12) + rng.uniform(-0.01, 0.06) * t / 12 + rng.normal(0, 1, n))


@pytest.mark.parametrize("season", ["JJA", "DJF", "year"])
def test_cell_p_equals_point_check(season):
    for seed in range(20):
        monthly = cell_monthly(seed)
        years, vals = grid.aggregate_seasonal(monthly, season, "mean", False)
        slope, p = grid.cell_trend(years, vals)

        py, pv = seasonal_series(monthly, season, "mean", grid.START + (season == "DJF"), grid.END,
                                 per_day=False, data_start_year=grid.START, data_start_month=1)
        point = analyze_trend(py, pv, min_years=15)
        assert p == pytest.approx(point.mk.p, rel=1e-12)
        assert slope == pytest.approx(point.sen.slope_per_decade, rel=1e-12)


def test_short_cell_is_nan_and_left_out():
    slope, p = grid.cell_trend(np.arange(2015, 2025.0), np.arange(10.0))
    assert np.isnan(slope) and np.isnan(p)
