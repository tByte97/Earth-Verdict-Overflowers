"""Trend estimators: Sen's slope with 95% CI, autocorrelation-corrected Mann-Kendall, and OLS with n_eff."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import math
from typing import Literal, Optional

import numpy as np
from scipy.stats import linregress, norm, rankdata, t as t_dist, theilslopes

_Z_975 = 1.959963984540054  # norm.ppf(0.975)


@dataclass(frozen=True)
class SenResult:
    slope_per_year: float
    slope_per_decade: float
    ci_low_per_year: float
    ci_high_per_year: float
    intercept_at_start: float


@dataclass(frozen=True)
class MKResult:
    p: float
    tau: float
    z: float
    correction: Literal["hamed_rao", "none"]
    ess: float


@dataclass(frozen=True)
class OLSResult:
    slope_per_year: float
    p: float
    r2: float
    n_eff: float
    residual_sd: float
    phi: float


@dataclass(frozen=True)
class TrendResult:
    n: int
    start_year: int
    end_year: int
    sen: SenResult
    mk: MKResult
    ols: OLSResult


def _filter_valid(
    years: Sequence[int], values: Sequence[Optional[float]]
) -> tuple[np.ndarray, np.ndarray]:
    """Filter out missing/non-finite observations and sort chronologically."""
    if len(years) != len(values):
        raise ValueError(f"years ({len(years)}) and values ({len(values)}) must have the same length")
    pairs = [
        (int(yr), float(val))
        for yr, val in zip(years, values)
        if val is not None and math.isfinite(float(val))
    ]
    pairs.sort(key=lambda pair: pair[0])
    if not pairs:
        return np.empty(0, dtype=float), np.empty(0, dtype=float)
    xs = np.array([p[0] for p in pairs], dtype=float)
    if np.any(np.diff(xs) <= 0):
        raise ValueError("years must be strictly increasing after filtering")
    ys = np.array([p[1] for p in pairs], dtype=float)
    return xs, ys


def _lag_acf_values(vals: np.ndarray, years: np.ndarray, max_lag: int) -> np.ndarray:
    """Compute sample lag-1..max_lag autocorrelations normalized by total sum of squares.

    Zero-padding missing years onto an integer-year grid ensures non-adjacent
    observations separated by a gap never enter as spurious consecutive pairs.
    """
    denom = float(np.sum(vals * vals))
    if denom <= 0.0 or max_lag < 1 or len(vals) < 2:
        return np.zeros(max(0, max_lag), dtype=float)

    yr_int = np.round(years).astype(int)
    span = int(yr_int[-1] - yr_int[0]) + 1
    k_eff = min(max_lag, span - 1)
    if k_eff < 1:
        return np.zeros(max_lag, dtype=float)

    if span == len(vals):
        grid = vals
    else:
        grid = np.zeros(span, dtype=float)
        grid[yr_int - yr_int[0]] = vals

    acfs = np.zeros(max_lag, dtype=float)
    for k in range(1, k_eff + 1):
        acfs[k - 1] = float(np.dot(grid[:-k], grid[k:])) / denom
    return acfs


def _ess_from_rank_acfs(n: int, acfs: np.ndarray) -> np.ndarray | float:
    """Compute clamped Hamed-Rao effective sample size inflation factor (>= 1.0).

    Combines the standard thresholded Hamed-Rao rank-ACF sum (|rho_k| > 1.96/sqrt(n))
    with a geometric AR(1) rank-ACF envelope driven by the Marriott-Pope
    bias-corrected positive lag-1 correlation r1_bc = clip((n*rho_1 + 1)/(n - 3), 0, 0.95).
    Both factors are clamped below at 1.0 to prevent negative or deflated variances.
    """
    if n <= 4:
        if acfs.ndim == 1:
            return 1.0
        return np.ones(acfs.shape[:-1], dtype=float)

    c = 2.0 / (n * (n - 1) * (n - 2))
    ks_full = np.arange(1, n - 1, dtype=float)
    w_full = (n - ks_full) * (n - ks_full - 1) * (n - ks_full - 2)

    rho1 = acfs[..., 0]
    r1_bc = np.clip((n * rho1 + 1.0) / (n - 3.0), 0.0, 0.95)
    ess_ar1 = 1.0 + c * np.sum((r1_bc[..., None] ** ks_full) * w_full, axis=-1)

    k_avail = acfs.shape[-1]
    crit = _Z_975 / math.sqrt(n)
    sig_acfs = np.where(np.abs(acfs) > crit, acfs, 0.0)
    ess_hr = 1.0 + c * np.sum(sig_acfs * w_full[:k_avail], axis=-1)

    ess = np.maximum(1.0, np.maximum(ess_ar1, ess_hr))
    return float(ess) if acfs.ndim == 1 else ess


def _mk_s_and_ties(y: np.ndarray) -> tuple[float, float]:
    """Compute Mann-Kendall S statistic and tie-corrected white-noise variance V0."""
    n = len(y)
    iu0, iu1 = np.triu_indices(n, k=1)
    dy = y[iu1] - y[iu0]
    s = float(np.sum(dy > 0) - np.sum(dy < 0))
    _, counts = np.unique(y, return_counts=True)
    tp = counts[counts > 1]
    tie_corr = float(np.sum(tp * (tp - 1) * (2 * tp + 5))) if len(tp) else 0.0
    var_0 = (n * (n - 1) * (2 * n + 5) - tie_corr) / 18.0
    return s, var_0


def sen_slope(
    years: Sequence[int],
    values: Sequence[Optional[float]],
    *,
    start_year: Optional[int] = None,
) -> SenResult:
    """Compute Sen's median pairwise slope, 95% confidence interval, and intercept."""
    x, y = _filter_valid(years, values)
    if len(y) < 2:
        raise ValueError("Need at least 2 valid observations for Sen's slope")
    ts = theilslopes(y, x, alpha=0.95)
    slope = float(ts.slope)
    ci_low = float(ts.low_slope) if math.isfinite(ts.low_slope) else slope
    ci_high = float(ts.high_slope) if math.isfinite(ts.high_slope) else slope
    ref_x = float(start_year) if start_year is not None else float(x[0])
    intercept = float(ts.intercept + slope * ref_x)
    return SenResult(
        slope_per_year=slope,
        slope_per_decade=slope * 10.0,
        ci_low_per_year=min(ci_low, ci_high),
        ci_high_per_year=max(ci_low, ci_high),
        intercept_at_start=intercept,
    )


def mann_kendall(
    years: Sequence[int],
    values: Sequence[Optional[float]],
    *,
    detrend_slope: Optional[float] = None,
) -> MKResult:
    """Autocorrelation-corrected Mann-Kendall trend test (Hamed-Rao clamped >= 1).

    Choice of correction vs Yue-Pilon TFPW:
    We use Hamed-Rao variance inflation (matching the ``correction="hamed_rao"``
    API contract without removing observations or altering Kendall's tau), clamped
    to ``ess >= 1.0`` and reinforced with a bias-corrected AR(1) rank-ACF envelope.
    Clamping eliminates negative/deflated variance NaN failures seen in sample
    high-lag correlations (e.g. Kharkiv JJA precip), while the AR(1) envelope keeps
    false positives <= 5% under moderate persistence (phi ~ 0.3) where raw
    sample rho_1 often sits just below the 1.96/sqrt(n) significance threshold.
    """
    x, y = _filter_valid(years, values)
    n = len(y)
    if n < 2:
        raise ValueError("Need at least 2 valid observations for Mann-Kendall")

    s, var_0 = _mk_s_and_ties(y)
    tau = float(s / (0.5 * n * (n - 1)))
    if var_0 <= 0.0:
        return MKResult(p=1.0, tau=tau, z=0.0, correction="hamed_rao", ess=1.0)

    if detrend_slope is None:
        detrend_slope = float(theilslopes(y, x, alpha=0.95).slope)

    resid = y - detrend_slope * x
    ranks_centered = rankdata(resid) - (n + 1.0) / 2.0
    acfs = _lag_acf_values(ranks_centered, x, max_lag=max(0, n - 2))
    ess = float(_ess_from_rank_acfs(n, acfs))

    var_s = var_0 * ess
    if s > 0.0:
        z = (s - 1.0) / math.sqrt(var_s)
    elif s < 0.0:
        z = (s + 1.0) / math.sqrt(var_s)
    else:
        z = 0.0
    p = float(2.0 * norm.sf(abs(z)))
    return MKResult(p=p, tau=tau, z=float(z), correction="hamed_rao", ess=ess)


def mann_kendall_batch_p(y_batch: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Vectorized Hamed-Rao MK p-values and S signs for contiguous simulated series.

    Shares ``_ess_from_rank_acfs`` with ``mann_kendall`` so power simulations match
    the exact production test on continuous AR(1)+trend realizations.
    """
    m, n = y_batch.shape
    if n < 5:
        raise ValueError("y_batch requires at least 5 time steps")

    x = np.arange(n, dtype=float)
    iu0, iu1 = np.triu_indices(n, k=1)
    dx = x[iu1] - x[iu0]
    dy = y_batch[:, iu1] - y_batch[:, iu0]

    s = np.sum(dy > 0.0, axis=1, dtype=float) - np.sum(dy < 0.0, axis=1, dtype=float)
    var_0 = n * (n - 1) * (2 * n + 5) / 18.0

    # Median of exact Sen slopes matches theilslopes(y, x).slope for continuous data.
    med_slope = np.median(dy / dx, axis=1)
    resid = y_batch - med_slope[:, None] * x[None, :]
    ranks = rankdata(resid, axis=1) - (n + 1.0) / 2.0
    denom = np.sum(ranks * ranks, axis=1)
    safe_denom = np.where(denom > 0.0, denom, 1.0)

    k_max = n - 2
    acfs = np.zeros((m, k_max), dtype=float)
    for k in range(1, k_max + 1):
        acfs[:, k - 1] = np.sum(ranks[:, :-k] * ranks[:, k:], axis=1) / safe_denom
    acfs = np.where((denom > 0.0)[:, None], acfs, 0.0)

    ess = _ess_from_rank_acfs(n, acfs)
    var_s = var_0 * ess
    z = np.where(
        s > 0.0,
        (s - 1.0) / np.sqrt(var_s),
        np.where(s < 0.0, (s + 1.0) / np.sqrt(var_s), 0.0),
    )
    p = 2.0 * norm.sf(np.abs(z))
    return p, s


def ols_effective(years: Sequence[int], values: Sequence[Optional[float]]) -> OLSResult:
    """OLS linear trend with AR(1) effective sample size adjustment n_eff = n(1-r1)/(1+r1).

    Negative residual lag-1 estimates keep n_eff at n so sampling noise does not
    inflate effective degrees of freedom above observed sample count n.
    """
    x, y = _filter_valid(years, values)
    n = len(y)
    if n < 3:
        raise ValueError("Need at least 3 valid observations for OLS effective test")

    lr = linregress(x, y)
    slope = float(lr.slope)
    intercept = float(lr.intercept)
    r2 = float(lr.rvalue ** 2) if math.isfinite(lr.rvalue) else 0.0

    res = y - (intercept + slope * x)
    res_centered = res - float(np.mean(res))
    r1 = float(_lag_acf_values(res_centered, x, max_lag=1)[0])
    phi = min(max(r1, 0.0), 0.9)
    residual_sd = float(np.std(res, ddof=2))

    if r1 > 0.0:
        n_eff = max(3.0, n * (1.0 - r1) / (1.0 + r1))
    else:
        n_eff = float(n)
    df = max(n_eff - 2.0, 1.0)

    if lr.stderr > 0.0 and math.isfinite(lr.stderr):
        t_stat = (slope / float(lr.stderr)) * math.sqrt(df / (n - 2.0))
        p = float(2.0 * t_dist.sf(abs(t_stat), df))
    else:
        p = 1.0 if slope == 0.0 else 0.0

    return OLSResult(
        slope_per_year=slope,
        p=p,
        r2=r2,
        n_eff=float(n_eff),
        residual_sd=residual_sd,
        phi=phi,
    )


def analyze_trend(
    years: Sequence[int],
    values: Sequence[Optional[float]],
    *,
    min_years: int = 3,
    start_year: Optional[int] = None,
) -> Optional[TrendResult]:
    """Run Sen, autocorrelation-corrected Mann-Kendall, and OLS effective analyses."""
    if min_years < 3:
        raise ValueError("min_years must be at least 3")
    x, y = _filter_valid(years, values)
    n = len(y)
    if n < min_years:
        return None

    ref_start = start_year if start_year is not None else int(x[0])
    sen = sen_slope(x, y, start_year=ref_start)
    mk = mann_kendall(x, y, detrend_slope=sen.slope_per_year)
    ols = ols_effective(x, y)
    return TrendResult(
        n=n,
        start_year=int(x[0]),
        end_year=int(x[-1]),
        sen=sen,
        mk=mk,
        ols=ols,
    )
