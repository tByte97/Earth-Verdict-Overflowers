"""Unit tests for seasonal aggregation (backend/app/stats/seasonal.py)."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.stats.seasonal import months_for_season, seasonal_series


def _monthly_grid(start_year: int, end_year: int, value_fn):
    out = []
    for yr in range(start_year, end_year + 1):
        for mo in range(1, 13):
            out.append(value_fn(yr, mo))
    return out


def test_djf_crosses_year_boundary():
    # Encode value = year * 100 + month so DJF components are unambiguous.
    monthly = _monthly_grid(1981, 1983, lambda yr, mo: float(yr * 100 + mo))
    years, vals = seasonal_series(monthly, "DJF", "mean", 1981, 1983)

    assert years == [1981, 1982, 1983]
    # Dec 1980 is outside 1981-01 start -> 1981 DJF must be None.
    assert vals[0] is None
    # DJF 1982 = (Dec 1981 + Jan 1982 + Feb 1982) / 3
    assert vals[1] == pytest.approx((198112 + 198201 + 198202) / 3.0)
    # DJF 1983 = (Dec 1982 + Jan 1983 + Feb 1983) / 3
    assert vals[2] == pytest.approx((198212 + 198301 + 198302) / 3.0)


def test_precip_sum_per_day_leap_year():
    # Constant 2.0 mm/day across non-leap 2023 and leap 2024 (from 1981-01).
    monthly = _monthly_grid(1981, 2024, lambda _yr, _mo: 2.0)

    years, annual = seasonal_series(monthly, "year", "sum", 2023, 2024, per_day=True)
    assert years == [2023, 2024]
    assert annual == [pytest.approx(2.0 * 365), pytest.approx(2.0 * 366)]

    _, feb_only = seasonal_series(monthly, 2, "sum", 2023, 2024, per_day=True)
    assert feb_only == [pytest.approx(2.0 * 28), pytest.approx(2.0 * 29)]

    _, djf_sum = seasonal_series(monthly, "DJF", "sum", 2023, 2024, per_day=True)
    # DJF 2023: 31+31+28=90 days; DJF 2024: 31+31+29=91 days
    assert djf_sum == [pytest.approx(2.0 * 90), pytest.approx(2.0 * 91)]


def test_single_month_and_missing_month_gives_none():
    monthly = _monthly_grid(1981, 1984, lambda _yr, mo: float(mo))
    # Remove July 1982 (index = (1982 - 1981)*12 + 6 = 18) and Mar 1983 (26).
    monthly[18] = None
    monthly[26] = float("nan")

    years, jja = seasonal_series(monthly, "JJA", "mean", 1981, 1984)
    assert years == [1981, 1982, 1983, 1984]
    assert jja[0] == pytest.approx((6 + 7 + 8) / 3.0)
    assert jja[1] is None
    assert jja[2] == pytest.approx((6 + 7 + 8) / 3.0)

    _, mar = seasonal_series(monthly, 3, "mean", 1981, 1984)
    assert mar == [3.0, 3.0, None, 3.0]


def test_invalid_season_and_agg_raise():
    with pytest.raises(ValueError):
        months_for_season("ABC")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        months_for_season(0)
    with pytest.raises(ValueError):
        months_for_season(13)
    with pytest.raises(ValueError):
        months_for_season(True)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        seasonal_series([1.0] * 12, "JJA", "median", 1981, 1981)  # type: ignore[arg-type]
