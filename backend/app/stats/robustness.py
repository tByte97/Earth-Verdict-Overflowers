"""Shifted-window robustness checks for trend verdicts."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Optional

from .trend import analyze_trend

DEFAULT_ALPHA = 0.05
MIN_WINDOW_YEARS = 15


@dataclass(frozen=True)
class RobustnessWindowResult:
    start_year: int
    end_year: int
    n: int
    p: float
    slope_per_decade: float
    significant: bool


@dataclass(frozen=True)
class RobustnessResult:
    windows: list[RobustnessWindowResult]
    significant: int
    total: int


def shifted_windows(
    start_year: int,
    end_year: int,
    *,
    min_years: int = MIN_WINDOW_YEARS,
) -> list[tuple[int, int]]:
    """Return up to 5 shifted start/end sub-windows of length >= min_years."""
    candidates = [
        (start_year, end_year),
        (start_year + 3, end_year),
        (start_year + 6, end_year),
        (start_year, end_year - 3),
        (start_year + 3, end_year - 3),
    ]
    return [(a, b) for a, b in candidates if b - a + 1 >= min_years]


def assess_robustness(
    years: Sequence[int],
    values: Sequence[Optional[float]],
    main_slope_per_year: float,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    *,
    alpha: float = DEFAULT_ALPHA,
    min_years: int = MIN_WINDOW_YEARS,
) -> RobustnessResult:
    """Evaluate shifted sub-windows and count significant same-sign trends."""
    if len(years) != len(values):
        raise ValueError("years and values must have the same length")
    if not years:
        return RobustnessResult(windows=[], significant=0, total=0)

    y0 = int(years[0]) if start_year is None else start_year
    y1 = int(years[-1]) if end_year is None else end_year

    out: list[RobustnessWindowResult] = []
    for win_start, win_end in shifted_windows(y0, y1, min_years=min_years):
        sub_pairs = [(yr, val) for yr, val in zip(years, values) if win_start <= yr <= win_end]
        if not sub_pairs:
            continue
        sub_years = [p[0] for p in sub_pairs]
        sub_values = [p[1] for p in sub_pairs]
        t_win = analyze_trend(sub_years, sub_values, min_years=3, start_year=win_start)
        if t_win is None:
            continue
        same_sign = (t_win.sen.slope_per_year * main_slope_per_year) > 0.0
        sig = bool(t_win.n >= min_years and t_win.mk.p < alpha and same_sign)
        out.append(
            RobustnessWindowResult(
                start_year=win_start,
                end_year=win_end,
                n=t_win.n,
                p=t_win.mk.p,
                slope_per_decade=t_win.sen.slope_per_decade,
                significant=sig,
            )
        )

    n_sig = sum(1 for w in out if w.significant)
    return RobustnessResult(windows=out, significant=n_sig, total=len(out))
