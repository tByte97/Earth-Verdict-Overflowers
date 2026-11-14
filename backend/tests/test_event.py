"""Unit tests for BACI event impact statistics (stats/event.py) and CO2 physics (stats/co2.py)."""
from __future__ import annotations

import math
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.stats.co2 import (
    RF_COEFF_MYHRE,
    TCR_CENTRAL,
    plant_contribution,
    summarize_global_co2,
    what_if_concentration,
)
from app.stats.event import MIN_PLACEBOS, analyze_event


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


def _ar1(rng: np.random.Generator, phi: float, n: int) -> np.ndarray:
    x = np.zeros(n)
    x[0] = rng.normal()
    for t in range(1, n):
        x[t] = phi * x[t - 1] + math.sqrt(1.0 - phi * phi) * rng.normal()
    return x


def test_step_change_detected():
    # 16 years (2005-01..2020-12), event at 2014-01 (index 108), window=3y (36m).
    # Fake dates every 12 months whose windows end before the event: 2008-01..2011-01 (4 dates).
    site = _seasonal_series(16, base=12.0, step_at=108, step_size=3.0, sd=0.35, seed=10)
    ctrl = _seasonal_series(16, base=8.0, sd=0.35, seed=11)
    res = analyze_event(site, ctrl, "2005-01", "2014-01", window_years=3)

    assert res.verdict == "clear_change"
    assert res.reason == "clear_change"
    assert res.direction == "increase"
    assert res.control_used is True
    assert res.effect == pytest.approx(3.0, abs=0.45)
    assert res.relative_change == pytest.approx(0.25, abs=0.05)
    assert res.p is not None and res.p < 0.001
    assert res.ci_low is not None and res.ci_high is not None and res.ci_low > 0.0
    assert res.bootstrap_ci_low is not None and res.bootstrap_ci_low > 0.0
    assert [pl.event_month for pl in res.placebo] == ["2008-01", "2009-01", "2010-01", "2011-01"]
    assert res.placebo_larger == 0
    assert res.sen_before is not None and res.sen_after is not None


def test_no_change_returns_not_proven():
    site = _seasonal_series(16, base=10.0, sd=0.5, seed=20)
    ctrl = _seasonal_series(16, base=10.0, sd=0.5, seed=21)
    res = analyze_event(site, ctrl, "2005-01", "2014-01", window_years=3)

    assert res.verdict == "not_proven"
    assert res.reason == "not_significant"
    assert res.p is not None and res.p >= 0.05


def test_smooth_trend_triggers_placebo_also_changes():
    # A steady trend at the site (not in control) produces a significant shift at the real date
    # and shifts of the same size at every fake date.
    site = _seasonal_series(16, base=10.0, trend_per_month=0.12, sd=0.8, seed=31)
    ctrl = _seasonal_series(16, base=10.0, sd=0.8, seed=32)
    res = analyze_event(site, ctrl, "2005-01", "2014-01", window_years=3)

    assert res.verdict == "not_proven"
    assert res.reason == "placebo_also_changes"
    assert res.placebo_larger >= 1


def test_control_removes_regional_shift():
    # A +4.0 regional shift hits BOTH site and control equally at 2016-01.
    site = _seasonal_series(16, base=10.0, regional_shift_at=108, regional_shift=4.0, sd=0.3, seed=40)
    ctrl = _seasonal_series(16, base=8.0, regional_shift_at=108, regional_shift=4.0, sd=0.3, seed=41)

    with_ctrl = analyze_event(site, ctrl, "2005-01", "2014-01", window_years=3)
    assert with_ctrl.verdict == "not_proven"
    assert with_ctrl.reason == "not_significant"
    assert with_ctrl.effect is not None and abs(with_ctrl.effect) < 0.4

    without_ctrl = analyze_event(site, None, "2005-01", "2014-01", window_years=3)
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
    # 6 years total -> 3y before + 3y after fits, but no non-overlapping fake date fits.
    site = _seasonal_series(6, base=10.0, step_at=36, step_size=5.0, sd=0.2, seed=60)
    ctrl = _seasonal_series(6, base=10.0, sd=0.2, seed=61)
    res = analyze_event(site, ctrl, "2010-01", "2013-01", window_years=3)
    assert res.verdict == "not_proven"
    assert res.reason == "no_placebo"
    assert res.placebo == []


def test_too_few_placebos_is_not_a_verdict():
    # 10 years, event 2016-01, w=3: a single fake date (2013-01) fits, below MIN_PLACEBOS.
    site = _seasonal_series(10, base=12.0, step_at=72, step_size=3.0, sd=0.35, seed=10)
    ctrl = _seasonal_series(10, base=8.0, sd=0.35, seed=11)
    res = analyze_event(site, ctrl, "2010-01", "2016-01", window_years=3)
    assert 0 < len(res.placebo) < MIN_PLACEBOS
    assert res.p is not None and res.p < 0.001
    assert res.verdict == "not_proven"
    assert res.reason == "no_placebo"


def test_placebo_counts_large_effects_even_if_not_significant():
    # A real +1.0 step after a noisy history: one fake date (2008-01) shows a shift as large as
    # the real one but is not significant on its own. It must still count against the event.
    site = _seasonal_series(16, base=12.0, step_at=108, step_size=1.0, sd=0.2, seed=70)
    rng = np.random.default_rng(0)
    for i in range(108):
        site[i] += float(rng.normal(0.0, 2.5))
    ctrl = _seasonal_series(16, base=8.0, sd=0.2, seed=72)
    res = analyze_event(site, ctrl, "2005-01", "2014-01", window_years=3)
    assert res.p is not None and res.p < 0.05
    big = [pl for pl in res.placebo if abs(pl.effect) >= abs(res.effect)]
    assert big and all(pl.p >= 0.05 for pl in big)
    assert res.placebo_larger == len(big)
    assert res.reason == "placebo_also_changes"


@pytest.mark.parametrize("window_years,event_month", [(1, "2015-03"), (3, "2013-08")])
def test_autocorrelated_noise_false_positive_rate(window_years: int, event_month: str):
    # No event, AR(1) noise with phi=0.6 at site and control: clear_change must stay near 5%.
    n_seeds, n_months = 300, 21 * 12
    hits = 0
    for seed in range(n_seeds):
        rng = np.random.default_rng(1000 + seed)
        site, ctrl = _ar1(rng, 0.6, n_months), _ar1(rng, 0.6, n_months)
        res = analyze_event(site.tolist(), ctrl.tolist(), "2005-01", event_month, window_years, n_bootstrap=20)
        hits += res.verdict == "clear_change"
    assert hits / n_seeds <= 0.06


@pytest.mark.parametrize("window_years,event_month", [(1, "2015-03"), (3, "2013-08")])
def test_smooth_trend_without_event_is_rarely_a_clear_change(window_years: int, event_month: str):
    # The site drifts 0.15 SD/yr against its control and nothing happens at the event date.
    # With only significant +/-12..36 month placebos, w=3 gave ~24% false clear_change here.
    n_seeds, n_months = 300, 21 * 12
    hits = 0
    for seed in range(n_seeds):
        rng = np.random.default_rng(5000 + seed)
        site = _ar1(rng, 0.3, n_months) + 0.15 * np.arange(n_months) / 12.0
        ctrl = _ar1(rng, 0.3, n_months)
        res = analyze_event(site.tolist(), ctrl.tolist(), "2005-01", event_month, window_years, n_bootstrap=20)
        hits += res.verdict == "clear_change"
    assert hits / n_seeds <= 0.12


def test_relative_change_hidden_for_near_zero_baseline():
    # SO2-like site: baseline around zero, a clear +1.0 step.
    site = _seasonal_series(16, base=0.02, amp=0.1, step_at=108, step_size=1.0, sd=0.3, seed=80)
    ctrl = _seasonal_series(16, base=0.0, amp=0.1, sd=0.3, seed=81)
    res = analyze_event(site, ctrl, "2005-01", "2014-01", window_years=3)
    assert res.effect is not None and res.effect > 0.5
    assert res.relative_change is None


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
        TCR_CENTRAL * math.log((426.0 + res.added_ppm.central) / 426.0) / math.log(2.0), rel=1e-6
    )

    wi = what_if_concentration(560.0, c0_ppm=280.0)
    assert wi.forcing_w_m2 == pytest.approx(5.35 * math.log(2.0), rel=1e-6)
    # TCR is the warming at CO2 doubling, by definition.
    assert wi.transient_warming_c.central == pytest.approx(TCR_CENTRAL, rel=1e-9)
    assert wi.transient_warming_c.low < wi.transient_warming_c.central < wi.transient_warming_c.high

    months = _months(1980, 10)
    # 2.0 ppm/yr trend + seasonal wave
    vals = [338.0 + 2.0 * (i // 12) + 2.5 * math.sin(2 * math.pi * (i % 12) / 12) for i in range(len(months))]
    summary = summarize_global_co2(months, vals, since_year=1980)
    assert summary.latest_month == "1989-12"
    assert summary.yoy_growth_ppm == pytest.approx(2.0, abs=1e-6)
    assert summary.sen_slope_ppm_per_year == pytest.approx(2.0, abs=1e-3)
