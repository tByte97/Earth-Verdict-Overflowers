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


def compute_detection(
    residual_sd: float,
    phi: float,
    slope_per_year: float,
    n_years: int,
    multipliers: Sequence[float] = DEFAULT_MULTIPLIERS,
) -> DetectionResult:
    """Build Detection metrics for frontend speed-multiplier controls."""
    phi_c = _clamp_phi(phi)
    mult_list = [float(m) for m in multipliers]
    return DetectionResult(
        residual_sd=float(residual_sd),
        phi=phi_c,
        slope_per_year=float(slope_per_year),
        n_years=int(n_years),
        multipliers=mult_list,
        years_needed=weatherhead_years_needed(
            residual_sd=residual_sd,
            phi=phi_c,
            slope_per_year=slope_per_year,
            multipliers=mult_list,
        ),
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
    n_sims: int = 80,
    max_n: int = 250,
    seed: int = 2026,
) -> Optional[int]:
    """Estimate additional years needed for the actual MK test to detect |slope_per_year|.

    Consistency rule fixing Weatherhead n* <= n ("wait 0") contradictions:
    Weatherhead et al. (1998) uses constant 3.3 (derived for 12 monthly points/year
    with asymptotic OLS errors), so on annual/seasonal series it can return n* <= n even
    when the actual Hamed-Rao Mann-Kendall test is non-significant. Here:
      - Returns None unless ``verdict == "not_proven"`` (and when ``reason == "sources_disagree"``
        or ``slope_per_year == 0``).
      - Otherwise runs a deterministic seeded Monte Carlo power search (with common random
        numbers across N) of the same vectorized ``mann_kendall_batch_p`` test under fitted
        stationary AR(1)(residual_sd, phi) noise + linear drift |slope_per_year|.
      - Searches integer total length N in [max(min_years, n_years + 1), max_n] for the
        smallest N achieving directional power >= target_power (default 0.80), returning
        ``N - n_years`` (always >= 1), or None if > ``max_n`` total years are needed.
    """
    if verdict != "not_proven" or reason == "sources_disagree":
        return None
    if not math.isfinite(slope_per_year) or slope_per_year == 0.0:
        return None
    if not math.isfinite(residual_sd) or residual_sd < 0.0:
        return None

    lo = max(min_years, int(n_years) + 1)
    if lo > max_n:
        return None
    if residual_sd == 0.0:
        return lo - int(n_years)

    phi_c = _clamp_phi(phi)
    infl = math.sqrt((1.0 + phi_c) / (1.0 - phi_c))
    # Annual OLS lower-bound feasibility guard avoids wasted simulation for near-zero trends.
    n_ols_est = ((2.8 * math.sqrt(12.0) * residual_sd / abs(slope_per_year)) * infl) ** (2.0 / 3.0)
    if n_ols_est > max_n * 1.25:
        return None

    rng = np.random.default_rng(seed)
    innov = rng.normal(0.0, 1.0, size=(n_sims, max_n))
    noise = np.empty((n_sims, max_n), dtype=float)
    noise[:, 0] = innov[:, 0] * residual_sd
    innov_sd = residual_sd * math.sqrt(max(1e-9, 1.0 - phi_c * phi_c))
    for t_idx in range(1, max_n):
        noise[:, t_idx] = phi_c * noise[:, t_idx - 1] + innov[:, t_idx] * innov_sd

    signal = abs(slope_per_year) * np.arange(max_n, dtype=float)
    y_full = noise + signal[None, :]

    def _power_at(n_len: int) -> float:
        p_vals, s_stats = mann_kendall_batch_p(y_full[:, :n_len])
        return float(np.mean((p_vals < alpha) & (s_stats > 0.0)))

    if _power_at(max_n) < target_power:
        return None
    if _power_at(lo) >= target_power:
        return lo - int(n_years)

    hi = max_n
    while lo < hi:
        mid = (lo + hi) // 2
        if _power_at(mid) >= target_power:
            hi = mid
        else:
            lo = mid + 1
    return lo - int(n_years)
