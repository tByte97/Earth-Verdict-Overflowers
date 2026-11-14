"""Unit tests for BACI event impact statistics (stats/event.py) and CO2 physics (stats/co2.py)."""
from __future__ import annotations

import math
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.stats.co2 import (
    F2X_CO2_AR6,
    RF_COEFF_MYHRE,
    TCR_CENTRAL,
    plant_contribution,
    summarize_global_co2,
    what_if_concentration,
)
from app.stats.event import analyze_event


def _months(start_year: int, n_years: int) -> list[str]:
    return [f"{start_year + i // 12:04d}-{i % 12 + 1:02d}" for i in range(n_years * 12)]


def _seasonal_series(
    n_years: int,
    *,
    base: float = 10.0,
    amp: float = 3.0,
    step_at: int | None = None,
    step_size: float = 0.0,
    trend_per_month: float = 0.0,
    regional_shift_at: int | None = None,
    regional_shift: float = 0.0,
    sd: float = 0.3,
    seed: int = 1,
) -> list[float]:
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n_years * 12):
        val = base + amp * math.sin(2.0 * math.pi * (i % 12) / 12.0) + trend_per_month * i
        if step_at is not None and i >= step_at:
            val += step_size
        if regional_shift_at is not None and i >= regional_shift_at:
            val += regional_shift
        val += float(rng.normal(0.0, sd))
        out.append(val)
    return out


def test_step_change_detected():
    # 10 years (2010-01..2019-12), event at 2016-01 (index 72), window=3y (36m).
    # Placebo at -36m (2013-01) has windows 2010-01..2012-12 vs 2013-01..2015-12 -> no step.
    site = _seasonal_series(10, base=12.0, step_at=72, step_size=3.0, sd=0.35, seed=10)
    ctrl = _seasonal_series(10, base=8.0, sd=0.35, seed=11)
    res = analyze_event(site, ctrl, "2010-01", "2016-01", window_years=3)

    assert res.verdict == "clear_change"
    assert res.reason == "clear_change"
    assert res.direction == "increase"
    assert res.control_used is True
    assert res.effect == pytest.approx(3.0, abs=0.45)
    assert res.relative_change == pytest.approx(0.25, abs=0.05)
    assert res.p is not None and res.p < 0.001
    assert res.ci_low is not None and res.ci_high is not None and res.ci_low > 0.0
    assert res.bootstrap_ci_low is not None and res.bootstrap_ci_low > 0.0
    assert len(res.placebo) == 1 and res.placebo[0].event_month == "2013-01"
    assert res.placebo_larger == 0
    assert res.sen_before is not None and res.sen_after is not None


def test_no_change_returns_not_proven():
    site = _seasonal_series(10, base=10.0, sd=0.5, seed=20)
    ctrl = _seasonal_series(10, base=10.0, sd=0.5, seed=21)
    res = analyze_event(site, ctrl, "2010-01", "2016-01", window_years=3)

    assert res.verdict == "not_proven"
    assert res.reason == "not_significant"
    assert res.p is not None and res.p >= 0.05


def test_smooth_trend_triggers_placebo_also_changes():
    # A steady trend at the site (not in control) produces a significant shift at the real date
    # and an equally large or larger significant shift at the shifted placebo date (-36m).
    site = _seasonal_series(10, base=10.0, trend_per_month=0.12, sd=0.8, seed=31)
    ctrl = _seasonal_series(10, base=10.0, sd=0.8, seed=32)
    res = analyze_event(site, ctrl, "2010-01", "2016-01", window_years=3)

    assert res.verdict == "not_proven"
    assert res.reason == "placebo_also_changes"
    assert res.placebo_larger >= 1


def test_control_removes_regional_shift():
    # A +4.0 regional shift hits BOTH site and control equally at 2016-01.
    site = _seasonal_series(10, base=10.0, regional_shift_at=72, regional_shift=4.0, sd=0.3, seed=40)
    ctrl = _seasonal_series(10, base=8.0, regional_shift_at=72, regional_shift=4.0, sd=0.3, seed=41)

    with_ctrl = analyze_event(site, ctrl, "2010-01", "2016-01", window_years=3)
    assert with_ctrl.verdict == "not_proven"
    assert with_ctrl.reason == "not_significant"
    assert with_ctrl.effect is not None and abs(with_ctrl.effect) < 0.4

    without_ctrl = analyze_event(site, None, "2010-01", "2016-01", window_years=3)
    assert without_ctrl.control_used is False
    assert without_ctrl.verdict == "clear_change"
    assert without_ctrl.effect == pytest.approx(4.0, abs=0.4)


def test_short_or_sparse_data_returns_too_short():
    # Fewer months than window requires
    site = [10.0] * 48
    res = analyze_event(site, None, "2015-01", "2017-01", window_years=3)
    assert res.verdict == "not_proven"
    assert res.reason == "too_short"
    assert res.effect is None

    # Enough length (10 years), but >40% missing in after window (<60% valid)
    site2 = _seasonal_series(10, base=10.0, sd=0.3, seed=50)
    for idx in range(72, 72 + 18):  # 18/36 missing -> 50% valid < 60%
        site2[idx] = None  # type: ignore[call-overload]
    res2 = analyze_event(site2, None, "2010-01", "2016-01", window_years=3)
    assert res2.verdict == "not_proven"
    assert res2.reason == "too_short"


def test_no_placebo_window_returns_no_placebo():
    # 6 years total -> 3y before + 3y after fits, but no -36/+36 non-overlapping placebo fits.
    site = _seasonal_series(6, base=10.0, step_at=36, step_size=5.0, sd=0.2, seed=60)
    ctrl = _seasonal_series(6, base=10.0, sd=0.2, seed=61)
    res = analyze_event(site, ctrl, "2010-01", "2013-01", window_years=3)
    assert res.verdict == "not_proven"
    assert res.reason == "no_placebo"
    assert res.placebo == []


def test_autocorrelated_noise_false_positive_rate():
    # AR(1) noise with phi=0.5 over 200 seeds must not produce >10% false clear_change.
    phi = 0.5
    innov_sd = math.sqrt(1.0 - phi * phi)
    false_positives = 0
    n_seeds = 200
    n_months = 10 * 12

    for seed in range(n_seeds):
        rng = np.random.default_rng(1000 + seed)
        s_noise = np.zeros(n_months)
        c_noise = np.zeros(n_months)
        for t in range(1, n_months):
            s_noise[t] = phi * s_noise[t - 1] + innov_sd * rng.normal()
            c_noise[t] = phi * c_noise[t - 1] + innov_sd * rng.normal()
        res = analyze_event(s_noise.tolist(), c_noise.tolist(), "2010-01", "2016-01", window_years=3)
        if res.verdict == "clear_change":
            false_positives += 1

    assert false_positives / n_seeds <= 0.10


def test_co2_physics_and_global_summary():
    # 10 Mt CO2/yr * 30 years = 0.3 Gt CO2
    res = plant_contribution(10.0, 30.0, c_now_ppm=426.0)
    assert res.total_emitted_gt == pytest.approx(0.3)
    assert res.added_ppm.central == pytest.approx(0.3 * 0.44 / 7.82, rel=1e-6)
    assert res.added_ppm.low < res.added_ppm.central < res.added_ppm.high
    assert res.added_forcing_w_m2.central == pytest.approx(
        RF_COEFF_MYHRE * math.log((426.0 + res.added_ppm.central) / 426.0), rel=1e-6
    )
    assert res.transient_warming_c.central == pytest.approx(
        TCR_CENTRAL * res.added_forcing_w_m2.central / F2X_CO2_AR6, rel=1e-6
    )

    wi = what_if_concentration(560.0, c0_ppm=280.0)
    assert wi.forcing_w_m2 == pytest.approx(5.35 * math.log(2.0), rel=1e-6)
    assert wi.transient_warming_c.central == pytest.approx(1.8 * wi.forcing_w_m2 / 3.93, rel=1e-6)
    assert wi.transient_warming_c.low < wi.transient_warming_c.central < wi.transient_warming_c.high

    months = _months(1980, 10)
    # 2.0 ppm/yr trend + seasonal wave
    vals = [338.0 + 2.0 * (i // 12) + 2.5 * math.sin(2 * math.pi * (i % 12) / 12) for i in range(len(months))]
    summary = summarize_global_co2(months, vals, since_year=1980)
    assert summary.latest_month == "1989-12"
    assert summary.yoy_growth_ppm == pytest.approx(2.0, abs=1e-6)
    assert summary.sen_slope_ppm_per_year == pytest.approx(2.0, abs=1e-3)
    assert summary.mk_p < 0.001
