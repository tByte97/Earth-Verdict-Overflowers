"""Monte Carlo false-positive control and power verification for the full verdict pipeline."""
import math
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.verdict import decide_verdict, evaluate_verdict


def _ar1_sample(rng: np.random.Generator, n: int, phi: float, sd: float = 1.0) -> np.ndarray:
    """Simulate a stationary AR(1) realization of length n with marginal std ``sd``."""
    innov_sd = sd * math.sqrt(max(0.0, 1.0 - phi * phi))
    out = np.empty(n, dtype=float)
    out[0] = rng.normal(0.0, sd)
    innov = rng.normal(0.0, innov_sd, size=n - 1)
    for idx in range(1, n):
        out[idx] = phi * out[idx - 1] + innov[idx - 1]
    return out


def test_false_positive_rate_ar1_1000_series():
    """1000 pure AR(1) noise series (phi=0.3, n=45) must confirm <= 5% of the time."""
    n_sims = 1000
    n_years = 45
    phi = 0.3
    years = list(range(1981, 1981 + n_years))
    rng = np.random.default_rng(2026)

    confirmed_increase = 0
    confirmed_change = 0
    mk_sig = 0

    for _ in range(n_sims):
        vals = _ar1_sample(rng, n_years, phi=phi, sd=1.0).tolist()
        ev_inc = evaluate_verdict(
            years, vals, direction="increase", start_year=1981, end_year=2025, compute_wait=False
        )
        if ev_inc.main.mk.p < 0.05:
            mk_sig += 1
        if ev_inc.verdict == "confirmed":
            confirmed_increase += 1
        verdict_chg, _ = decide_verdict(
            n_years=ev_inc.main.n,
            mk_p=ev_inc.main.mk.p,
            slope_per_year=ev_inc.main.sen.slope_per_year,
            direction="change",
            robust_significant=ev_inc.robustness.significant,
            witness_agree=ev_inc.witness_agreement,
        )
        if verdict_chg == "confirmed":
            confirmed_change += 1

    fp_inc = confirmed_increase / n_sims
    fp_chg = confirmed_change / n_sims
    print(
        f"\nAR(1) phi={phi}, n={n_years}, sims={n_sims}: "
        f"confirmed(increase)={fp_inc:.3%} ({confirmed_increase}/{n_sims}), "
        f"confirmed(change)={fp_chg:.3%} ({confirmed_change}/{n_sims}), "
        f"raw_mk_sig={mk_sig / n_sims:.3%}"
    )
    assert fp_inc <= 0.05
    assert fp_chg <= 0.05


def test_power_check_slope_005_sd_08():
    """Real trend (slope=0.05/yr, sd=0.8, n=45) should be confirmed in most simulations."""
    n_sims = 200
    n_years = 45
    years = list(range(1981, 1981 + n_years))
    t_idx = np.arange(n_years, dtype=float)
    rng = np.random.default_rng(2027)

    confirmed = 0
    for _ in range(n_sims):
        vals = (0.05 * t_idx + rng.normal(0.0, 0.8, size=n_years)).tolist()
        ev = evaluate_verdict(
            years, vals, direction="increase", start_year=1981, end_year=2025, compute_wait=False
        )
        if ev.verdict == "confirmed":
            confirmed += 1

    power = confirmed / n_sims
    print(f"\nPower (slope=0.05/yr, sd=0.8, n={n_years}, sims={n_sims}): {power:.3%}")
    assert power >= 0.85
