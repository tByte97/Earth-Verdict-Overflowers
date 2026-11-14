"""BACI (Before-After-Control-Impact) monthly event impact statistics with placebo checks.

Fake event dates ("placebos") are placed every 12 months wherever both of their windows fit in
the record without overlapping the real before/after span. A fake date counts against the real
event when its effect is at least as large in absolute value, whether or not it is significant on
its own: a smooth trend gives fake dates the same effect as the real one, so they must be allowed
to match it. A verdict needs at least MIN_PLACEBOS fake dates.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import math
from typing import Literal, Optional

import numpy as np
from scipy.stats import t as t_dist

from .trend import sen_slope

ALPHA = 0.05
MIN_WINDOW_COVERAGE = 0.60
BOOTSTRAP_BLOCK_MONTHS = 6
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20261114
PLACEBO_STEP_MONTHS = 12
MIN_PLACEBOS = 3

EventVerdict = Literal["clear_change", "not_proven"]
EventDirection = Literal["increase", "decrease", "none"]
EventReason = Literal[
    "clear_change",
    "not_significant",
    "placebo_also_changes",
    "too_short",
    "no_placebo",
]


@dataclass(frozen=True)
class WindowStats:
    start: str
    end: str
    mean: Optional[float]
    n: int


@dataclass(frozen=True)
class EventSenSlope:
    slope_per_year: float
    ci_low: float
    ci_high: float


@dataclass(frozen=True)
class PlaceboResult:
    event_month: str
    effect: float
    p: float


@dataclass(frozen=True)
class EventStatsResult:
    before: WindowStats
    after: WindowStats
    effect: Optional[float]
    ci_low: Optional[float]
    ci_high: Optional[float]
    bootstrap_ci_low: Optional[float]
    bootstrap_ci_high: Optional[float]
    p: Optional[float]
    relative_change: Optional[float]
    placebo: list[PlaceboResult]
    placebo_larger: int
    verdict: EventVerdict
    direction: EventDirection
    reason: EventReason
    control_used: bool
    sen_before: Optional[EventSenSlope]
    sen_after: Optional[EventSenSlope]


def _parse_ym(ym: str) -> tuple[int, int]:
    parts = ym.split("-")
    if len(parts) != 2:
        raise ValueError(f"Invalid YYYY-MM string: {ym!r}")
    year, month = int(parts[0]), int(parts[1])
    if not 1 <= month <= 12:
        raise ValueError(f"Month must be 1..12 in {ym!r}")
    return year, month


def _ym_to_index(ym: str, start_ym: str) -> int:
    y, m = _parse_ym(ym)
    y0, m0 = _parse_ym(start_ym)
    return (y - y0) * 12 + (m - m0)


def _index_to_ym(idx: int, start_ym: str) -> str:
    y0, m0 = _parse_ym(start_ym)
    total = y0 * 12 + (m0 - 1) + idx
    y, m_zero = divmod(total, 12)
    return f"{y:04d}-{m_zero + 1:02d}"


def _to_float_array(values: Sequence[Optional[float]]) -> np.ndarray:
    arr = np.full(len(values), np.nan, dtype=float)
    for idx, val in enumerate(values):
        if val is not None:
            fval = float(val)
            if math.isfinite(fval):
                arr[idx] = fval
    return arr


def _lag1_acf_clamped(window: np.ndarray) -> float:
    """Lag-1 autocorrelation of a monthly window, bias-corrected and clipped to [0, 0.95].

    The plain estimate is biased low on 12-36 points (by about -(1 + 4 r1) / n), which would
    overstate the effective sample size and give too many false "clear change" results.
    """
    valid = np.isfinite(window)
    n_valid = int(np.sum(valid))
    if n_valid < 3 or len(window) < 2:
        return 0.0
    mean_val = float(np.nanmean(window))
    centered = np.where(valid, window - mean_val, 0.0)
    denom = float(np.dot(centered, centered))
    if denom <= 0.0:
        return 0.0
    r1 = float(np.dot(centered[:-1], centered[1:])) / denom
    r1 += (1.0 + 4.0 * r1) / n_valid
    return min(max(r1, 0.0), 0.95)


def _moving_block_bootstrap_ci(
    d_before: np.ndarray,
    d_after: np.ndarray,
    *,
    block_size: int,
    n_resamples: int,
    seed: int,
) -> tuple[float, float]:
    """Compute moving-block bootstrap 95% CI for mean(d_after) - mean(d_before)."""
    rng = np.random.default_rng(seed)

    def _boot_means(arr: np.ndarray) -> np.ndarray:
        length = len(arr)
        eff_block = min(block_size, length)
        n_blocks = math.ceil(length / eff_block)
        max_start = length - eff_block
        starts = rng.integers(0, max_start + 1, size=(n_resamples, n_blocks))
        offsets = np.arange(eff_block)[None, None, :]
        idx = (starts[:, :, None] + offsets).reshape(n_resamples, n_blocks * eff_block)[:, :length]
        samples = arr[idx]
        valid = np.isfinite(samples)
        counts = np.sum(valid, axis=1)
        sums = np.sum(np.where(valid, samples, 0.0), axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(counts > 0, sums / counts, np.nan)

    diffs = _boot_means(d_after) - _boot_means(d_before)
    finite = diffs[np.isfinite(diffs)]
    if len(finite) == 0:
        obs = float(np.nanmean(d_after) - np.nanmean(d_before))
        return obs, obs
    low, high = np.percentile(finite, [2.5, 97.5])
    return float(low), float(high)


@dataclass(frozen=True)
class _WindowEval:
    valid_b: int
    valid_a: int
    site_before_mean: Optional[float]
    site_after_mean: Optional[float]
    effect: float
    ci_low: float
    ci_high: float
    bootstrap_ci_low: Optional[float]
    bootstrap_ci_high: Optional[float]
    p: float
    relative_change: Optional[float]


def _evaluate_baci_window(
    site_arr: np.ndarray,
    ctrl_arr: Optional[np.ndarray],
    event_idx: int,
    w_months: int,
    *,
    min_coverage: float,
    compute_bootstrap: bool,
    block_size: int,
    n_bootstrap: int,
    bootstrap_seed: int,
) -> Optional[_WindowEval]:
    b_start = event_idx - w_months
    a_end = event_idx + w_months
    if b_start < 0 or a_end > len(site_arr):
        return None

    sb = site_arr[b_start:event_idx]
    sa = site_arr[event_idx:a_end]

    site_clim = np.full(12, np.nan, dtype=float)
    for m in range(12):
        vals = sb[m::12]
        if np.any(np.isfinite(vals)):
            site_clim[m] = float(np.nanmean(vals))

    clim_idx = np.arange(w_months) % 12
    site_anom_b = sb - site_clim[clim_idx]
    site_anom_a = sa - site_clim[clim_idx]

    if ctrl_arr is not None:
        cb = ctrl_arr[b_start:event_idx]
        ca = ctrl_arr[event_idx:a_end]
        ctrl_clim = np.full(12, np.nan, dtype=float)
        for m in range(12):
            vals = cb[m::12]
            if np.any(np.isfinite(vals)):
                ctrl_clim[m] = float(np.nanmean(vals))
        d_before = site_anom_b - (cb - ctrl_clim[clim_idx])
        d_after = site_anom_a - (ca - ctrl_clim[clim_idx])
    else:
        d_before = site_anom_b
        d_after = site_anom_a

    valid_b_mask = np.isfinite(d_before)
    valid_a_mask = np.isfinite(d_after)
    n_b = int(np.sum(valid_b_mask))
    n_a = int(np.sum(valid_a_mask))

    if n_b < min_coverage * w_months or n_a < min_coverage * w_months:
        return None
    if n_b < 2 or n_a < 2:
        return None

    vals_b = d_before[valid_b_mask]
    vals_a = d_after[valid_a_mask]
    effect = float(np.mean(vals_a) - np.mean(vals_b))

    site_before_mean = float(np.nanmean(sb)) if np.any(np.isfinite(sb)) else None
    site_after_mean = float(np.nanmean(sa)) if np.any(np.isfinite(sa)) else None

    var_b = float(np.var(vals_b, ddof=1))
    var_a = float(np.var(vals_a, ddof=1))
    r1_b = _lag1_acf_clamped(d_before)
    r1_a = _lag1_acf_clamped(d_after)

    n_eff_b = max(2.0, n_b * (1.0 - r1_b) / (1.0 + r1_b))
    n_eff_a = max(2.0, n_a * (1.0 - r1_a) / (1.0 + r1_a))

    vb = var_b / n_eff_b
    va = var_a / n_eff_a
    se = math.sqrt(vb + va)

    # A percentage only makes sense against a baseline clearly above zero (SO2 columns can be
    # near zero or negative over clean areas, where a percentage explodes).
    relative_change = None
    sb_valid = sb[np.isfinite(sb)]
    if site_before_mean is not None and site_before_mean > 0.0 and len(sb_valid) > 1:
        se_base = float(np.std(sb_valid, ddof=1)) / math.sqrt(n_eff_b)
        if site_before_mean >= 3.0 * se_base:
            relative_change = effect / site_before_mean

    if se <= 0.0:
        p = 1.0 if effect == 0.0 else 0.0
        ci_low = effect
        ci_high = effect
    else:
        df = ((vb + va) ** 2) / ((vb ** 2) / (n_eff_b - 1.0) + (va ** 2) / (n_eff_a - 1.0))
        t_stat = effect / se
        p = float(2.0 * t_dist.sf(abs(t_stat), df))
        t_crit = float(t_dist.ppf(0.975, df))
        ci_low = effect - t_crit * se
        ci_high = effect + t_crit * se

    boot_low = boot_high = None
    if compute_bootstrap:
        boot_low, boot_high = _moving_block_bootstrap_ci(
            d_before,
            d_after,
            block_size=block_size,
            n_resamples=n_bootstrap,
            seed=bootstrap_seed,
        )

    return _WindowEval(
        valid_b=n_b,
        valid_a=n_a,
        site_before_mean=site_before_mean,
        site_after_mean=site_after_mean,
        effect=effect,
        ci_low=ci_low,
        ci_high=ci_high,
        bootstrap_ci_low=boot_low,
        bootstrap_ci_high=boot_high,
        p=p,
        relative_change=relative_change,
    )


def _window_sen_slope(site_arr: np.ndarray, start_idx: int, end_idx: int) -> Optional[EventSenSlope]:
    if start_idx < 0 or end_idx > len(site_arr) or end_idx - start_idx < 2:
        return None
    sub = site_arr[start_idx:end_idx]
    vals = [float(v) if math.isfinite(v) else None for v in sub]
    if sum(v is not None for v in vals) < 2:
        return None
    res = sen_slope(list(range(len(vals))), vals, start_year=0)
    return EventSenSlope(
        slope_per_year=res.slope_per_year * 12.0,
        ci_low=res.ci_low_per_year * 12.0,
        ci_high=res.ci_high_per_year * 12.0,
    )


def analyze_event(
    site: Sequence[Optional[float]],
    control: Optional[Sequence[Optional[float]]],
    start_month: str,
    event_month: str,
    window_years: int = 3,
    *,
    alpha: float = ALPHA,
    min_coverage: float = MIN_WINDOW_COVERAGE,
    block_size: int = BOOTSTRAP_BLOCK_MONTHS,
    n_bootstrap: int = BOOTSTRAP_RESAMPLES,
    bootstrap_seed: int = BOOTSTRAP_SEED,
    compute_bootstrap: bool = True,
    compute_sen: bool = True,
) -> EventStatsResult:
    """Run BACI event impact analysis with deseasonalisation, lag-1 Welch t, bootstrap, and placebos."""
    if not 1 <= window_years <= 5:
        raise ValueError(f"window_years must be in 1..5, got {window_years}")
    if len(site) == 0:
        raise ValueError("site series must not be empty")
    if control is not None and len(control) != len(site):
        raise ValueError("control series must match site length when provided")

    site_arr = _to_float_array(site)
    ctrl_arr = _to_float_array(control) if control is not None else None
    control_used = ctrl_arr is not None

    event_idx = _ym_to_index(event_month, start_month)
    w_months = window_years * 12
    b_start = event_idx - w_months
    a_end = event_idx + w_months

    before_start_ym = _index_to_ym(b_start, start_month)
    before_end_ym = _index_to_ym(event_idx - 1, start_month)
    after_start_ym = _index_to_ym(event_idx, start_month)
    after_end_ym = _index_to_ym(a_end - 1, start_month)

    sen_b = _window_sen_slope(site_arr, max(0, b_start), min(len(site_arr), event_idx)) if compute_sen else None
    sen_a = _window_sen_slope(site_arr, max(0, event_idx), min(len(site_arr), a_end)) if compute_sen else None

    main = _evaluate_baci_window(
        site_arr,
        ctrl_arr,
        event_idx,
        w_months,
        min_coverage=min_coverage,
        compute_bootstrap=compute_bootstrap,
        block_size=block_size,
        n_bootstrap=n_bootstrap,
        bootstrap_seed=bootstrap_seed,
    )

    if main is None:
        sb_slice = site_arr[max(0, b_start):max(0, min(len(site_arr), event_idx))]
        sa_slice = site_arr[max(0, event_idx):max(0, min(len(site_arr), a_end))]
        sb_mean = float(np.nanmean(sb_slice)) if np.any(np.isfinite(sb_slice)) else None
        sa_mean = float(np.nanmean(sa_slice)) if np.any(np.isfinite(sa_slice)) else None
        n_sb = int(np.sum(np.isfinite(sb_slice)))
        n_sa = int(np.sum(np.isfinite(sa_slice)))
        return EventStatsResult(
            before=WindowStats(start=before_start_ym, end=before_end_ym, mean=sb_mean, n=n_sb),
            after=WindowStats(start=after_start_ym, end=after_end_ym, mean=sa_mean, n=n_sa),
            effect=None,
            ci_low=None,
            ci_high=None,
            bootstrap_ci_low=None,
            bootstrap_ci_high=None,
            p=None,
            relative_change=None,
            placebo=[],
            placebo_larger=0,
            verdict="not_proven",
            direction="none",
            reason="too_short",
            control_used=control_used,
            sen_before=sen_b,
            sen_after=sen_a,
        )

    placebos: list[PlaceboResult] = []
    n_steps = len(site_arr) // PLACEBO_STEP_MONTHS + 1
    for k in range(-n_steps, n_steps + 1):
        if k == 0:
            continue
        fe = event_idx + k * PLACEBO_STEP_MONTHS
        fb_start = fe - w_months
        fa_end = fe + w_months
        if fb_start < 0 or fa_end > len(site_arr):
            continue
        # Both fake windows must lie entirely before the real event or entirely after its after-window.
        if not (fa_end <= event_idx or fb_start >= a_end):
            continue
        pl_eval = _evaluate_baci_window(
            site_arr,
            ctrl_arr,
            fe,
            w_months,
            min_coverage=min_coverage,
            compute_bootstrap=False,
            block_size=block_size,
            n_bootstrap=n_bootstrap,
            bootstrap_seed=bootstrap_seed,
        )
        if pl_eval is not None:
            placebos.append(
                PlaceboResult(
                    event_month=_index_to_ym(fe, start_month),
                    effect=pl_eval.effect,
                    p=pl_eval.p,
                )
            )

    placebo_larger = sum(1 for pl in placebos if abs(pl.effect) >= abs(main.effect))
    direction: EventDirection = (
        "increase" if main.effect > 0.0 else "decrease" if main.effect < 0.0 else "none"
    )
    ci_excludes_zero = main.ci_low > 0.0 or main.ci_high < 0.0

    if len(placebos) < MIN_PLACEBOS:
        verdict: EventVerdict = "not_proven"
        reason: EventReason = "no_placebo"
    elif main.p >= alpha or not ci_excludes_zero:
        verdict = "not_proven"
        reason = "not_significant"
    elif placebo_larger > 0:
        verdict = "not_proven"
        reason = "placebo_also_changes"
    else:
        verdict = "clear_change"
        reason = "clear_change"

    return EventStatsResult(
        before=WindowStats(
            start=before_start_ym,
            end=before_end_ym,
            mean=main.site_before_mean,
            n=main.valid_b,
        ),
        after=WindowStats(
            start=after_start_ym,
            end=after_end_ym,
            mean=main.site_after_mean,
            n=main.valid_a,
        ),
        effect=main.effect,
        ci_low=main.ci_low,
        ci_high=main.ci_high,
        bootstrap_ci_low=main.bootstrap_ci_low,
        bootstrap_ci_high=main.bootstrap_ci_high,
        p=main.p,
        relative_change=main.relative_change,
        placebo=placebos,
        placebo_larger=placebo_larger,
        verdict=verdict,
        direction=direction,
        reason=reason,
        control_used=control_used,
        sen_before=sen_b,
        sen_after=sen_a,
    )


@dataclass(frozen=True)
class ProfilePoint:
    event_month: str
    effect: Optional[float]
    ci_low: Optional[float]
    ci_high: Optional[float]
    p: Optional[float]
    verdict: EventVerdict
    reason: EventReason
    n_placebo: int
    placebo_larger: int


def event_profile(
    site: Sequence[Optional[float]],
    control: Optional[Sequence[Optional[float]]],
    start_month: str,
    window_years: int,
    *,
    alpha: float = ALPHA,
    min_coverage: float = MIN_WINDOW_COVERAGE,
) -> list[ProfilePoint]:
    """The same verdict for every event month whose windows fit the record.

    Uses exactly the rules of ``analyze_event`` (placebos included) but skips the bootstrap and
    Sen slopes, which do not affect the verdict, so a slider can show how the answer depends on
    the chosen month.
    """
    n = len(site)
    w = window_years * 12
    out: list[ProfilePoint] = []
    for idx in range(w, n - w + 1):
        ym = _index_to_ym(idx, start_month)
        r = analyze_event(site, control, start_month, ym, window_years, alpha=alpha,
                          min_coverage=min_coverage, compute_bootstrap=False, compute_sen=False)
        out.append(ProfilePoint(event_month=ym, effect=r.effect, ci_low=r.ci_low, ci_high=r.ci_high, p=r.p,
                                verdict=r.verdict, reason=r.reason, n_placebo=len(r.placebo),
                                placebo_larger=r.placebo_larger))
    return out
