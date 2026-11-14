"""Prefix trend checks for the educational record-length slider, not new verdicts."""
from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Optional

from .trend import analyze_trend


def detection_history(
    years: Sequence[int], values: Sequence[Optional[float]], *,
    alpha: float, min_observations: int,
) -> dict:
    """Use the production Sen/MK method on each prefix, preserving calendar gaps.

    Input values are the same unrounded annual aggregates used for the main trend.
    No power simulation, robustness decision, station verdict or future data is used.
    Keep p at received precision; the main API's mk.p is rounded to three significant digits.
    """
    if not years or len(years) != len(values):
        raise ValueError("History needs non-empty, equally sized years and values")
    if any(right <= left for left, right in zip(years, years[1:])):
        raise ValueError("History years must be strictly increasing")
    if not 0 < alpha < 1 or min_observations < 3:
        raise ValueError("Invalid significance threshold or minimum observations")
    by_year = dict(zip(years, values))
    xs, ys, points = [], [], []
    valid_count = 0
    for end in range(years[0], years[-1] + 1):
        value = by_year.get(end)
        if value is not None and not math.isfinite(float(value)):
            raise ValueError("History observations must be finite or None")
        xs.append(end)
        ys.append(value)
        valid_count += value is not None
        trend = analyze_trend(xs, ys, min_years=min_observations, start_year=years[0])
        points.append(dict(
            end_year=end, n_observations=valid_count,
            p=None if trend is None else trend.mk.p,
            correction=None if trend is None else trend.mk.correction,
            status="short_series" if trend is None else "ok",
        ))
    return dict(alpha=alpha, min_observations=min_observations,
                method="sen_mann_kendall", start_year=years[0], points=points)
