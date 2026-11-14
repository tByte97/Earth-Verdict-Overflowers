"""Pure-function climate trend statistics package for Earth Verdict."""
from .extrapolation import build_extrapolation
from .fdr import benjamini_hochberg, bh_adjusted_p, bh_fdr
from .robustness import (
    MIN_WINDOW_YEARS,
    RobustnessResult,
    RobustnessWindowResult,
    assess_robustness,
    shifted_windows,
)
from .seasonal import (
    SEASON_LABELS,
    SEASON_MONTHS,
    months_for_season,
    season_label,
    seasonal_series,
)
from .trend import (
    MKResult,
    OLSResult,
    SenResult,
    TrendResult,
    analyze_trend,
    mann_kendall,
    ols_effective,
    sen_slope,
)
from .wait import (
    DEFAULT_MULTIPLIERS,
    DetectionResult,
    compute_detection,
    estimate_years_to_wait,
    weatherhead_years_needed,
)

__all__ = [
    "DEFAULT_MULTIPLIERS",
    "DetectionResult",
    "MIN_WINDOW_YEARS",
    "MKResult",
    "OLSResult",
    "RobustnessResult",
    "RobustnessWindowResult",
    "SEASON_LABELS",
    "SEASON_MONTHS",
    "SenResult",
    "TrendResult",
    "analyze_trend",
    "assess_robustness",
    "benjamini_hochberg",
    "bh_adjusted_p",
    "bh_fdr",
    "build_extrapolation",
    "compute_detection",
    "estimate_years_to_wait",
    "mann_kendall",
    "months_for_season",
    "ols_effective",
    "season_label",
    "seasonal_series",
    "sen_slope",
    "shifted_windows",
    "weatherhead_years_needed",
]
