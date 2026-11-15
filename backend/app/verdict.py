"""Verdict decision logic and witness agreement evaluation."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import math
from typing import Literal, Optional

from .stats.robustness import MIN_WINDOW_YEARS, RobustnessResult, assess_robustness, required_windows
from .stats.trend import TrendResult, analyze_trend
from .stats.wait import DetectionResult, compute_detection, estimate_years_to_wait

ALPHA = 0.05
MIN_YEARS = MIN_WINDOW_YEARS  # one constant: the verdict and every shifted window need 15 years
MIN_WITNESS_COVERAGE = 0.6

ClaimDirection = Literal["increase", "decrease", "change"]
VerdictKind = Literal["confirmed", "refuted", "not_proven"]
VerdictReason = Literal[
    "significant_trend",
    "opposite_trend",
    "not_significant",
    "short_series",
    "sources_disagree",
    "not_robust",
    "no_variation",
]
WitnessAgreement = Literal["agree", "one_source", "disagree", "no_station"]


@dataclass(frozen=True)
class VerdictEvaluation:
    main: TrendResult
    robustness: RobustnessResult
    witness_trend: Optional[TrendResult]
    witness_coverage: Optional[float]
    witness_agreement: WitnessAgreement
    verdict: VerdictKind
    reason: VerdictReason
    years_to_wait: Optional[int]
    detection: DetectionResult


def sig3(p_value: float) -> float:
    """Format p-value to three significant digits (e.g. 1.23e-07 rather than 0.0)."""
    return float(f"{p_value:.3g}")


def direction_matches(direction: ClaimDirection, slope_per_year: float) -> bool:
    """Return True if observed slope direction matches the claimed direction."""
    if direction == "increase":
        return slope_per_year > 0.0
    if direction == "decrease":
        return slope_per_year < 0.0
    if direction == "change":
        return slope_per_year != 0.0
    raise ValueError(f"Unknown claim direction: {direction!r}")


def witness_agreement(
    main_slope_per_year: float,
    witness_mk_p: Optional[float],
    witness_slope_per_year: Optional[float],
    *,
    alpha: float = ALPHA,
) -> WitnessAgreement:
    """Classify ground-station witness agreement with the primary trend."""
    if witness_mk_p is None or witness_slope_per_year is None:
        return "no_station"
    same_sign = (witness_slope_per_year * main_slope_per_year) > 0.0
    if witness_mk_p < alpha and same_sign:
        return "agree"
    if witness_mk_p < alpha and not same_sign:
        return "disagree"
    return "one_source"


def decide_verdict(
    *,
    n_years: int,
    mk_p: float,
    slope_per_year: float,
    direction: ClaimDirection,
    robust_significant: int,
    witness_agree: WitnessAgreement,
    robust_total: int = 5,
    constant: bool = False,
    alpha: float = ALPHA,
    min_years: int = MIN_YEARS,
    robust_need: Optional[int] = None,
) -> tuple[VerdictKind, VerdictReason]:
    """Determine claim verdict and reason from trend, robustness, and witness evidence.

    robust_need=None takes the rule from required_windows(robust_total); an explicit number
    overrides it (threshold experiments in tools/experiments/robust_threshold.py).
    """
    if n_years < min_years:
        return "not_proven", "short_series"
    if constant:
        return "not_proven", "no_variation"
    if mk_p >= alpha or slope_per_year == 0.0:
        return "not_proven", "not_significant"
    need = required_windows(robust_total) if robust_need is None else robust_need
    if robust_significant < need:
        return "not_proven", "not_robust"
    if witness_agree == "disagree":
        return "not_proven", "sources_disagree"
    if direction_matches(direction, slope_per_year):
        return "confirmed", "significant_trend"
    return "refuted", "opposite_trend"


def evaluate_verdict(
    years: Sequence[int],
    values: Sequence[Optional[float]],
    *,
    direction: ClaimDirection,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    witness_years: Optional[Sequence[int]] = None,
    witness_values: Optional[Sequence[Optional[float]]] = None,
    alpha: float = ALPHA,
    min_years: int = MIN_YEARS,
    robust_need: Optional[int] = None,
    min_witness_coverage: float = MIN_WITNESS_COVERAGE,
    compute_wait: bool = True,
) -> VerdictEvaluation:
    """Run the full statistical verdict pipeline on an annual/seasonal series."""
    if not years:
        raise ValueError("years must not be empty")
    y0 = int(years[0]) if start_year is None else int(start_year)
    y1 = int(years[-1]) if end_year is None else int(end_year)

    main = analyze_trend(years, values, min_years=3, start_year=y0)
    if main is None:
        raise ValueError("Need at least 3 valid observations to evaluate verdict")

    # Too short a record is "short_series" before any shifted window is tried.
    if main.n < min_years:
        rob = RobustnessResult(windows=[], significant=0, total=0)
    else:
        rob = assess_robustness(
            years,
            values,
            main.sen.slope_per_year,
            start_year=y0,
            end_year=y1,
            alpha=alpha,
            min_years=min_years,
        )
    finite = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    constant = len(finite) >= min_years and max(finite) == min(finite)

    witness_trend: Optional[TrendResult] = None
    cov: Optional[float] = None
    if witness_years is not None and witness_values is not None and len(witness_values) > 0:
        valid_count = sum(
            v is not None and math.isfinite(float(v)) for v in witness_values
        )
        cov = valid_count / len(witness_values)
        if cov >= min_witness_coverage:
            witness_trend = analyze_trend(
                witness_years,
                witness_values,
                min_years=min_years,
                start_year=y0,
            )

    w_agree = witness_agreement(
        main.sen.slope_per_year,
        witness_trend.mk.p if witness_trend else None,
        witness_trend.sen.slope_per_year if witness_trend else None,
        alpha=alpha,
    )

    verdict, reason = decide_verdict(
        n_years=main.n,
        mk_p=main.mk.p,
        slope_per_year=main.sen.slope_per_year,
        direction=direction,
        robust_significant=rob.significant,
        witness_agree=w_agree,
        robust_total=rob.total,
        constant=constant,
        alpha=alpha,
        min_years=min_years,
        robust_need=robust_need,
    )

    # Детекція — симуляція потужності (~1 с); compute_wait=False вимикає її разом із wait
    # (масові симуляції в тестах і сітка на глобусі цього не потребують).
    if compute_wait:
        detection = compute_detection(
            residual_sd=main.ols.residual_sd,
            phi=main.ols.phi,
            slope_per_year=main.sen.slope_per_year,
            n_years=main.n,
            alpha=alpha,
            min_years=min_years,
        )
    else:
        detection = DetectionResult(
            residual_sd=float(main.ols.residual_sd), phi=float(min(max(main.ols.phi, 0.0), 0.9)),
            slope_per_year=float(main.sen.slope_per_year), n_years=int(main.n),
            multipliers=[0.5, 0.75, 1.0, 1.5, 2.0], years_needed=[None] * 5,
        )

    wait = (
        estimate_years_to_wait(
            verdict=verdict,
            slope_per_year=main.sen.slope_per_year,
            residual_sd=main.ols.residual_sd,
            phi=main.ols.phi,
            n_years=main.n,
            reason=reason,
            alpha=alpha,
            min_years=min_years,
        )
        if compute_wait
        else None
    )

    return VerdictEvaluation(
        main=main,
        robustness=rob,
        witness_trend=witness_trend,
        witness_coverage=cov,
        witness_agreement=w_agree,
        verdict=verdict,
        reason=reason,
        years_to_wait=wait,
        detection=detection,
    )
