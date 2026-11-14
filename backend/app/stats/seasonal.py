"""Seasonal aggregation from monthly climate series to one value per year."""
from __future__ import annotations

import calendar
import math
from collections.abc import Sequence
from typing import Literal, Optional, Union

Season = Union[Literal["year", "DJF", "MAM", "JJA", "SON"], int]
AggKind = Literal["mean", "sum"]

SEASON_MONTHS: dict[str, tuple[int, ...]] = {
    "year": tuple(range(1, 13)),
    "DJF": (12, 1, 2),
    "MAM": (3, 4, 5),
    "JJA": (6, 7, 8),
    "SON": (9, 10, 11),
}

SEASON_LABELS: dict[str, str] = {
    "year": "Whole year",
    "DJF": "Winter (DJF)",
    "MAM": "Spring (MAM)",
    "JJA": "Summer (JJA)",
    "SON": "Autumn (SON)",
}


def months_for_season(season: Season) -> tuple[int, ...]:
    """Return the calendar month numbers (1..12) for a named season or single month."""
    if not isinstance(season, bool) and isinstance(season, int):
        if 1 <= season <= 12:
            return (season,)
        raise ValueError(f"Month index must be in 1..12, got {season}")
    if isinstance(season, str) and season in SEASON_MONTHS:
        return SEASON_MONTHS[season]
    raise ValueError(f"Unknown season: {season!r}")


def season_label(season: Season) -> str:
    """Human-readable label for a season or calendar month."""
    if not isinstance(season, bool) and isinstance(season, int):
        months = months_for_season(season)
        return calendar.month_name[months[0]]
    months_for_season(season)
    return SEASON_LABELS[season]


def seasonal_series(
    monthly: Sequence[Optional[float]],
    season: Season,
    agg: AggKind,
    year_from: int,
    year_to: int,
    *,
    per_day: bool = False,
    data_start_year: int = 1981,
    data_start_month: int = 1,
) -> tuple[list[int], list[Optional[float]]]:
    """Aggregate monthly observations into one value per target year.

    For DJF of year Y, December comes from year Y-1 and Jan/Feb from year Y.
    When ``agg == "sum"`` and ``per_day=True``, monthly rates (e.g. mm/day) are
    multiplied by the actual days in that calendar month (accounting for leap years).
    Any missing or non-finite month in the season sets that year's value to ``None``.
    """
    if agg not in ("mean", "sum"):
        raise ValueError(f"agg must be 'mean' or 'sum', got {agg!r}")
    if year_to < year_from:
        return [], []

    months = months_for_season(season)
    n_monthly = len(monthly)
    years = list(range(year_from, year_to + 1))
    out: list[Optional[float]] = []

    for y in years:
        acc = 0.0
        complete = True
        for m in months:
            yy = y - 1 if (season == "DJF" and m == 12) else y
            idx = (yy - data_start_year) * 12 + (m - data_start_month)
            if idx < 0 or idx >= n_monthly:
                complete = False
                break
            raw = monthly[idx]
            if raw is None:
                complete = False
                break
            val = float(raw)
            if not math.isfinite(val):
                complete = False
                break
            if agg == "sum" and per_day:
                val *= calendar.monthrange(yy, m)[1]
            acc += val

        if not complete:
            out.append(None)
        elif agg == "sum":
            out.append(acc)
        else:
            out.append(acc / len(months))

    return years, out
