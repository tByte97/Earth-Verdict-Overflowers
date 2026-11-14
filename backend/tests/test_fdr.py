"""Unit tests for Benjamini-Hochberg FDR control (backend/app/stats/fdr.py)."""
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.stats.fdr import benjamini_hochberg, bh_adjusted_p


def test_bh_classic_1995_paper_example():
    """Table 1 from Benjamini & Hochberg (1995), m=15, q=0.05 -> 4 rejections."""
    p_vals = [
        0.0001, 0.0004, 0.0019, 0.0095, 0.0201,
        0.0278, 0.0298, 0.0344, 0.0459, 0.3240,
        0.4262, 0.5719, 0.6528, 0.7590, 1.0000,
    ]
    # Raw p < 0.05 has 9 hits; BH at q=0.05 has k=4 (0.0095 <= 4/15 * 0.05 = 0.01333,
    # while for k=5, 0.0201 > 5/15 * 0.05 = 0.01667).
    sig = benjamini_hochberg(p_vals, q=0.05)
    assert sig.dtype == bool
    assert sig.tolist() == [True] * 4 + [False] * 11


def test_bh_unsorted_input_preserves_original_positions():
    """Known 5-element example in scrambled order."""
    # Sorted: 0.001 (k=1 <= 0.01), 0.008 (k=2 <= 0.02), 0.039 (k=3 > 0.03), 0.041, 0.20
    p_vals = [0.039, 0.008, 0.20, 0.001, 0.041]
    sig = benjamini_hochberg(p_vals, q=0.05)
    assert sig.tolist() == [False, True, False, True, False]


def test_bh_step_up_property():
    """When p_(2) > 2/m*q but p_(3) <= 3/m*q, step-up rejects all i <= 3."""
    # m=4, q=0.05 -> thresholds: 0.0125, 0.025, 0.0375, 0.05
    p_vals = [0.029, 0.005, 0.40, 0.030]
    sig = benjamini_hochberg(p_vals, q=0.05)
    assert sig.tolist() == [True, True, False, True]
    adj = bh_adjusted_p(p_vals)
    assert np.all((adj <= 0.05) == sig)


def test_bh_edge_cases():
    assert benjamini_hochberg([], q=0.05).tolist() == []
    assert benjamini_hochberg([0.5, 0.8, 0.9], q=0.05).tolist() == [False, False, False]
    assert benjamini_hochberg([0.001, 0.002, 0.003], q=0.05).tolist() == [True, True, True]

    # NaNs are ignored in m and marked False
    sig_nan = benjamini_hochberg([0.001, np.nan, 0.008, 0.039, 0.041, 0.20], q=0.05)
    assert sig_nan.tolist() == [True, False, True, False, False, False]

    with pytest.raises(ValueError):
        benjamini_hochberg([0.01, 0.02], q=0.0)
    with pytest.raises(ValueError):
        benjamini_hochberg([0.01, 0.02], q=1.0)
