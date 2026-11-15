"""Detection wait-time estimation (Weatherhead et al. 1998 + consistent MK power simulation)."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import math
from typing import Optional

import numpy as np

from .trend import mann_kendall_batch_p

DEFAULT_MULTIPLIERS: tuple[float, ...] = (0.5, 0.75, 1.0, 1.5, 2.0)


@dataclass(frozen=True)
class DetectionResult:
    residual_sd: float
    phi: float
    slope_per_year: float
    n_years: int
    multipliers: list[float]
    years_needed: list[Optional[float]]


def _clamp_phi(phi: float) -> float:
    return min(max(float(phi), 0.0), 0.9)


def weatherhead_years_needed(
    residual_sd: float,
    phi: float,
    slope_per_year: float,
    multipliers: Sequence[float] = DEFAULT_MULTIPLIERS,
) -> list[Optional[float]]:
    """Compute Weatherhead et al. (1998) detection horizon n* for speed multipliers k.

    Formula: n* = ((3.3 * residual_sd / |k * slope_per_year|) * sqrt((1 + phi) / (1 - phi)))^(2/3).
    Returns None for any multiplier where detection is undefined (zero/non-finite slope).
    """
    if (
        not math.isfinite(slope_per_year)
        or slope_per_year == 0.0
        or not math.isfinite(residual_sd)
        or residual_sd < 0.0
    ):
        return [None for _ in multipliers]

    phi_c = _clamp_phi(phi)
    infl = math.sqrt((1.0 + phi_c) / (1.0 - phi_c))
    out: list[Optional[float]] = []
    for mult in multipliers:
        if mult == 0.0 or not math.isfinite(mult):
            out.append(None)
            continue
        n_star = ((3.3 * residual_sd / abs(mult * slope_per_year)) * infl) ** (2.0 / 3.0)
        out.append(round(n_star, 1))
    return out


def power_years_needed(
    slope_per_year: float,
    residual_sd: float,
    phi: float,
    multipliers: Sequence[float] = DEFAULT_MULTIPLIERS,
    *,
    alpha: float = 0.05,
    min_years: int = 15,
    target_power: float = 0.80,
    n_sims: int = 200,
    max_n: int = 250,
    seed: int = 2026,
) -> list[Optional[int]]:
    """Total years N at which the production MK test detects a trend of speed k·|slope|.

    One engine for both the slider (`Detection.years_needed`) and `years_to_wait`, so the two
    can never contradict each other. For each multiplier k: smallest N in [min_years, max_n]
    where a seeded AR(1)(residual_sd, phi) noise + drift k·|slope| series is found significant
    in the right direction in >= target_power of simulations. Common random numbers across N
    and k keep the result deterministic and monotone in practice. None = slope is zero or
    more than max_n years would be needed.
    """
    mults = [float(m) for m in multipliers]
    if (not math.isfinite(slope_per_year) or slope_per_year == 0.0
            or not math.isfinite(residual_sd) or residual_sd < 0.0):
        return [None for _ in mults]
    if residual_sd == 0.0:
        return [min_years if (k != 0.0 and math.isfinite(k)) else None for k in mults]

    phi_c = _clamp_phi(phi)
    rng = np.random.default_rng(seed)
    innov = rng.normal(0.0, 1.0, size=(n_sims, max_n))
    noise = np.empty((n_sims, max_n), dtype=float)
    noise[:, 0] = innov[:, 0] * residual_sd
    innov_sd = residual_sd * math.sqrt(max(1e-9, 1.0 - phi_c * phi_c))
    for t_idx in range(1, max_n):
        noise[:, t_idx] = phi_c * noise[:, t_idx - 1] + innov[:, t_idx] * innov_sd
    t = np.arange(max_n, dtype=float)

    out: list[Optional[int]] = []
    for k in mults:
        if k == 0.0 or not math.isfinite(k):
            out.append(None)
            continue
        y_full = noise + (abs(k * slope_per_year) * t)[None, :]

        def power_at(n_len: int) -> float:
            p_vals, s_stats = mann_kendall_batch_p(y_full[:, :n_len])
            return float(np.mean((p_vals < alpha) & (s_stats > 0.0)))

        lo, hi = min_years, max_n
        if power_at(hi) < target_power:
            out.append(None)
            continue
        if power_at(lo) >= target_power:
            out.append(lo)
            continue
        while lo < hi:
            mid = (lo + hi) // 2
            if power_at(mid) >= target_power:
                hi = mid
            else:
                lo = mid + 1
        out.append(lo)
    return out


def compute_detection(
    residual_sd: float,
    phi: float,
    slope_per_year: float,
    n_years: int,
    multipliers: Sequence[float] = DEFAULT_MULTIPLIERS,
    *,
    alpha: float = 0.05,
    min_years: int = 15,
) -> DetectionResult:
    """Detection metrics for the speed slider; same engine as `estimate_years_to_wait`."""
    phi_c = _clamp_phi(phi)
    mult_list = [float(m) for m in multipliers]
    needed = power_years_needed(slope_per_year, residual_sd, phi_c, mult_list,
                                alpha=alpha, min_years=min_years)
    return DetectionResult(
        residual_sd=float(residual_sd),
        phi=phi_c,
        slope_per_year=float(slope_per_year),
        n_years=int(n_years),
        multipliers=mult_list,
        years_needed=[None if v is None else float(v) for v in needed],
    )


def estimate_years_to_wait(
    verdict: str,
    slope_per_year: float,
    residual_sd: float,
    phi: float,
    n_years: int,
    *,
    reason: Optional[str] = None,
    alpha: float = 0.05,
    min_years: int = 15,
    target_power: float = 0.80,
    n_sims: int = 200,
    max_n: int = 250,
    seed: int = 2026,
) -> Optional[int]:
    """Extra years until the MK test would usually (>= 80%) detect the observed pace.

    Defined as ``power_years_needed(k=1) - n_years`` — exactly the slider value at ×1 minus
    the years we already have, so slider and verdict always agree. None when:
      - verdict is not ``not_proven``, or the reason is ``sources_disagree`` or ``no_variation``;
      - slope is zero, or more than ``max_n`` total years would be needed;
      - the needed length is already reached (N <= n): at this pace the trend is usually
        detectable by now, so "wait" would be misleading — the observed slope is likely
        overstated by noise. The frontend then shows the slider without a wait number.
    """
    if verdict != "not_proven" or reason in ("sources_disagree", "no_variation"):
        return None
    (needed,) = power_years_needed(slope_per_year, residual_sd, phi, [1.0], alpha=alpha,
                                   min_years=min_years, target_power=target_power,
                                   n_sims=n_sims, max_n=max_n, seed=seed)
    if needed is None or needed <= int(n_years):
        return None
    return needed - int(n_years)
