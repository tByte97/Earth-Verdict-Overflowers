"""Tests for detection wait times, extrapolation, robustness, and verdicts."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.stats.extrapolation import build_extrapolation
from app.stats.robustness import shifted_windows
from app.stats.wait import compute_detection, estimate_years_to_wait
from app.verdict import decide_verdict, witness_agreement


def test_detection_years_needed_monotone_and_zero_slope():
    det = compute_detection(residual_sd=0.94, phi=0.0, slope_per_year=0.0651, n_years=45)
    assert det.multipliers == [0.5, 0.75, 1.0, 1.5, 2.0]
    assert all(v is not None for v in det.years_needed)
    # Faster trend never needs more years
    assert all(a >= b for a, b in zip(det.years_needed, det.years_needed[1:]))
    # Kyiv-like heat trend is detectable within the 45 years we have
    assert det.years_needed[2] <= 45
    det_zero = compute_detection(residual_sd=1.0, phi=0.2, slope_per_year=0.0, n_years=45)
    assert det_zero.years_needed == [None, None, None, None, None]


def test_years_to_wait_matches_slider_at_x1():
    # The verdict's wait and the slider at x1 come from the same engine and must agree.
    for sd, phi, slope, n in [(1.0, 0.0, 0.02, 45), (95.0, 0.1, 2.18, 45), (2.6, 0.2, -0.0378, 44)]:
        det = compute_detection(residual_sd=sd, phi=phi, slope_per_year=slope, n_years=n)
        wait = estimate_years_to_wait("not_proven", slope, sd, phi, n, reason="not_significant")
        needed = det.years_needed[2]
        if needed is None or needed <= n:
            assert wait is None
        else:
            assert wait == int(needed) - n and wait >= 1


def test_years_to_wait_none_when_already_enough_years():
    # Strong trend: at this pace 45 years are enough, so "wait" would be misleading.
    assert estimate_years_to_wait("not_proven", 0.0651, 0.94, 0.0, 45, reason="not_significant") is None


def test_years_to_wait_deterministic_and_autocorrelation_increases_it():
    a = estimate_years_to_wait("not_proven", 0.02, 1.0, 0.0, 45, reason="not_significant")
    assert a is not None and a == estimate_years_to_wait("not_proven", 0.02, 1.0, 0.0, 45, reason="not_significant")
    b = estimate_years_to_wait("not_proven", 0.02, 1.0, 0.4, 45, reason="not_significant")
    assert b is not None and b > a


def test_years_to_wait_none_for_other_verdicts():
    assert estimate_years_to_wait("confirmed", 0.06, 0.9, 0.0, 45) is None
    assert estimate_years_to_wait("refuted", 0.06, 0.9, 0.0, 45) is None
    assert estimate_years_to_wait("not_proven", 0.06, 0.9, 0.0, 45, reason="sources_disagree") is None
    assert estimate_years_to_wait("not_proven", 0.0, 1.0, 0.0, 45) is None


def test_extrapolation_paths_and_ci_bounds():
    ext = build_extrapolation(
        slope_per_year=0.1,
        ci_low_per_year=0.05,
        ci_high_per_year=0.15,
        intercept_at_start=10.0,
        start_year=1981,
        end_year=2025,
        horizon_year=2050,
        decimals=2,
    )
    assert ext["from_year"] == 2025
    assert ext["from_value"] == pytest.approx(10.0 + 0.1 * 44)
    assert ext["years"][0] == 2025 and ext["years"][-1] == 2050
    assert len(ext["years"]) == 26

    by_id = {p["id"]: p for p in ext["paths"]}
    assert list(by_id) == ["stop", "slower", "same", "faster"]
    assert all(v == ext["from_value"] for v in by_id["stop"]["central"])
    assert by_id["same"]["label"] == "Same pace as 1981\u20132025"
    assert by_id["same"]["central"][-1] == pytest.approx(ext["from_value"] + 0.1 * 25)
    assert by_id["slower"]["central"][-1] == pytest.approx(ext["from_value"] + 0.05 * 25)
    assert by_id["faster"]["central"][-1] == pytest.approx(ext["from_value"] + 0.15 * 25)
    for path in ext["paths"]:
        for lo, mid, hi in zip(path["low"], path["central"], path["high"]):
            assert lo <= mid <= hi


def test_shifted_windows_and_verdict_rules():
    assert shifted_windows(1981, 2025) == [
        (1981, 2025),
        (1984, 2025),
        (1987, 2025),
        (1981, 2022),
        (1984, 2022),
    ]
    assert shifted_windows(2008, 2025) == [
        (2008, 2025),
        (2011, 2025),
        (2008, 2022),
    ]

    assert witness_agreement(0.05, None, None) == "no_station"
    assert witness_agreement(0.05, 0.01, 0.06) == "agree"
    assert witness_agreement(0.05, 0.01, -0.02) == "disagree"
    assert witness_agreement(0.05, 0.25, -0.02) == "one_source"
    # Zero witness slope is never same-sign even if statistically anomalous
    assert witness_agreement(0.05, 0.01, 0.0) == "disagree"

    assert decide_verdict(
        n_years=14, mk_p=0.001, slope_per_year=0.1, direction="increase",
        robust_significant=5, witness_agree="no_station",
    ) == ("not_proven", "short_series")
    assert decide_verdict(
        n_years=45, mk_p=0.08, slope_per_year=0.1, direction="increase",
        robust_significant=5, witness_agree="no_station",
    ) == ("not_proven", "not_significant")
    assert decide_verdict(
        n_years=45, mk_p=0.01, slope_per_year=0.1, direction="increase",
        robust_significant=3, witness_agree="no_station",
    ) == ("not_proven", "not_robust")
    assert decide_verdict(
        n_years=45, mk_p=0.01, slope_per_year=0.1, direction="increase",
        robust_significant=4, witness_agree="disagree",
    ) == ("not_proven", "sources_disagree")
    assert decide_verdict(
        n_years=45, mk_p=0.01, slope_per_year=0.1, direction="increase",
        robust_significant=4, witness_agree="agree",
    ) == ("confirmed", "significant_trend")
    assert decide_verdict(
        n_years=45, mk_p=0.01, slope_per_year=-0.1, direction="increase",
        robust_significant=4, witness_agree="no_station",
    ) == ("refuted", "opposite_trend")
