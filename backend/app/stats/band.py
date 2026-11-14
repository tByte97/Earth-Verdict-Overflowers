"""Chart geometry for the trend line: the 95% band and the baseline mean (pure, no network)."""
from __future__ import annotations

from collections.abc import Sequence
from statistics import median
from typing import Optional

BASELINE_START, BASELINE_END = 1991, 2020     # WMO climatological normal
BASELINE_MIN_YEARS = 24                       # 80% of 30 years


def sen_band(
    valid_years: Sequence[int],
    *,
    slope_per_year: float,
    ci_low_per_year: float,
    ci_high_per_year: float,
    intercept_at_start: float,
    start_year: int,
    end_year: int,
    decimals: int,
) -> tuple[float, float, list[dict]]:
    """Return (pivot_year, pivot_value, band) for the Sen line.

    Sen's line passes through the median of the years and the median of the values (the pivot).
    The band is the fan of lines through the pivot with the lowest and highest slope of the 95%
    interval: narrow at the centre of the record, widest at its ends. It shows the uncertainty of
    the slope only, not of single years. `mid` is the Sen line itself, so a chart needs no maths.
    """
    pivot_year = float(median(valid_years))
    pivot_value = intercept_at_start + slope_per_year * (pivot_year - start_year)
    band = []
    for year in range(start_year, end_year + 1):
        dt = year - pivot_year
        a, b = pivot_value + ci_low_per_year * dt, pivot_value + ci_high_per_year * dt
        band.append(dict(year=year, low=round(min(a, b), decimals + 1),
                         mid=round(pivot_value + slope_per_year * dt, decimals + 1),
                         high=round(max(a, b), decimals + 1)))
    return pivot_year, round(pivot_value, decimals + 1), band


def baseline_mean(years: Sequence[int], values: Sequence[Optional[float]], decimals: int) -> dict:
    """Mean for centring year colours: the 1991-2020 normal when the series covers it well
    (at least 24 of 30 years), otherwise the mean of the whole series shown."""
    pairs = [(y, v) for y, v in zip(years, values) if v is not None]
    normal = [v for y, v in pairs if BASELINE_START <= y <= BASELINE_END]
    if len(normal) >= BASELINE_MIN_YEARS:
        return dict(kind="normal_1991_2020", period=f"{BASELINE_START}-{BASELINE_END}",
                    mean=round(sum(normal) / len(normal), decimals + 1), n_years=len(normal))
    allv = [v for _, v in pairs]
    return dict(kind="series_mean", period=f"{pairs[0][0]}-{pairs[-1][0]}",
                mean=round(sum(allv) / len(allv), decimals + 1), n_years=len(allv))
