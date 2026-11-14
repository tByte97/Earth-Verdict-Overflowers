"""Stylised trend extrapolations to a future horizon (e.g. 2050)."""
from __future__ import annotations

from typing import Any

EXTRAPOLATION_NOTE = (
    "What-if line, not a forecast: it only shows where the trend would go at this pace. "
    "For physically based futures see the climate-model scenarios."
)


def build_extrapolation(
    slope_per_year: float,
    ci_low_per_year: float,
    ci_high_per_year: float,
    intercept_at_start: float,
    start_year: int,
    end_year: int,
    *,
    horizon_year: int = 2050,
    decimals: int = 1,
) -> dict[str, Any]:
    """Project Sen's trend and 95% slope CI forward from end_year under four pace scenarios."""
    if horizon_year < end_year:
        raise ValueError(f"horizon_year ({horizon_year}) must be >= end_year ({end_year})")

    fut = list(range(end_year, horizon_year + 1))
    y_end = intercept_at_start + slope_per_year * (end_year - start_year)
    slope_lo = min(ci_low_per_year, ci_high_per_year)
    slope_hi = max(ci_low_per_year, ci_high_per_year)

    pace_specs = (
        ("stop", "The change stops", 0.0),
        ("slower", "Half as fast", 0.5),
        ("same", f"Same pace as {start_year}\u2013{end_year}", 1.0),
        ("faster", "1.5\u00d7 faster", 1.5),
    )

    paths: list[dict[str, Any]] = []
    for path_id, label, mult in pace_specs:
        paths.append(
            {
                "id": path_id,
                "label": label,
                "multiplier": mult,
                "central": [round(y_end + mult * slope_per_year * (yr - end_year), decimals) for yr in fut],
                "low": [round(y_end + mult * slope_lo * (yr - end_year), decimals) for yr in fut],
                "high": [round(y_end + mult * slope_hi * (yr - end_year), decimals) for yr in fut],
            }
        )

    return {
        "note": EXTRAPOLATION_NOTE,
        "from_year": int(end_year),
        "from_value": round(y_end, decimals),
        "years": fut,
        "paths": paths,
    }
