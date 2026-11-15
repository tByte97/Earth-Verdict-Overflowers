"""tools/build_grid_years.py: year-by-year anomalies for the globe timeline."""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from build_grid_years import WINDOW, year_anomalies  # noqa: E402


def cell(lat, monthly_value):
    """A cell whose every month of year y has the value monthly_value(y)."""
    return {"lat": lat, "lon": 30.0, "monthly": [monthly_value(y) for y in range(1981, 2026) for _ in range(12)]}


def test_anomalies_are_relative_to_each_cells_own_baseline():
    warm = cell(50.0, lambda y: 20.0 + (1.0 if y >= 2021 else 0.0))       # flat, then one degree up
    cold = cell(46.0, lambda y: 5.0 - (2.0 if y >= 2021 else 0.0))
    out = year_anomalies([warm, cold], "JJA", "mean", False, digits=2)
    assert out["years"][0] == 1981 and out["years"][-1] == 2025
    assert out["anomaly"][out["years"].index(2000)] == [0.0, 0.0]
    assert out["anomaly"][-1] == [1.0, -2.0]
    # The mean is weighted by cell area (cos latitude), so it sits nearer the southern cell's value than -0.5.
    assert -0.6 < out["mean"][-1] < -0.5
    assert out["normal"] == pytest.approx(12.3, abs=0.2)


def test_smoothed_view_needs_a_full_window_and_ranks_run_from_the_highest_year():
    rising = cell(50.0, lambda y: float(y - 1981))
    out = year_anomalies([rising], "year", "mean", False, digits=2)
    assert out["mean_smooth"][WINDOW - 2] is None and out["mean_smooth"][WINDOW - 1] is not None
    assert out["anomaly_smooth"][-1][0] == pytest.approx(sum(out["anomaly"][i][0] for i in range(-WINDOW, 0)) / WINDOW, abs=0.01)
    assert out["rank"][-1] == 1 and out["rank"][0] == len(out["years"])


def test_cell_without_enough_baseline_years_stays_empty_and_winter_starts_a_year_later():
    gappy = {"lat": 50.0, "lon": 30.0, "monthly": [None if 1995 <= y <= 2015 else 1.0 for y in range(1981, 2026) for _ in range(12)]}
    out = year_anomalies([gappy, cell(50.0, lambda y: 3.0)], "DJF", "mean", False, digits=2)
    assert out["years"][0] == 1982
    assert all(row[0] is None for row in out["anomaly"]) and all(row[1] == 0.0 for row in out["anomaly"])
    assert out["mean"][0] == 0.0


def test_halo_cells_do_not_change_core_means_or_ranks():
    core = [cell(50.0, lambda y: float(y - 1981)), cell(46.0, lambda y: float(2 * (y - 1981)))]
    halo = [cell(41.0, lambda y: -999.0 if y == 2024 else 0.0), cell(55.5, lambda y: 999.0)]
    base = year_anomalies(core, "JJA", "mean", False, digits=2)
    with_halo = year_anomalies(core + halo, "JJA", "mean", False, digits=2)
    for key in ("mean", "rank", "mean_smooth", "normal"):
        assert with_halo[key] == base[key]
