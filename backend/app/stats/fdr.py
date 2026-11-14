"""Поправка Бенджаміні — Хохберга (BH-FDR) для множинних перевірок гіпотез."""
from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike


def benjamini_hochberg(p_values: ArrayLike, q: float = 0.05) -> np.ndarray:
    """Повертає булевий масив значущості за процедурою BH step-up на рівні FDR = q.

    Для m скінченних p-значень впорядковує їх p_(1) <= ... <= p_(m), знаходить
    найбільше k таке, що p_(k) <= (k / m) * q, і відхиляє нульову гіпотезу для всіх
    i = 1..k. Нескінченні значення (NaN) отримують False і не входять у m.
    """
    if not (0.0 < q < 1.0):
        raise ValueError(f"q must be in (0, 1), got {q}")

    p = np.asarray(p_values, dtype=float)
    if p.ndim != 1:
        raise ValueError("p_values must be a 1-D array")

    result = np.zeros(p.shape, dtype=bool)
    finite_mask = np.isfinite(p)
    finite_idx = np.flatnonzero(finite_mask)
    m = len(finite_idx)
    if m == 0:
        return result

    p_finite = p[finite_idx]
    order = np.argsort(p_finite, kind="mergesort")
    p_sorted = p_finite[order]

    ranks = np.arange(1, m + 1, dtype=float)
    thresholds = (ranks / m) * q
    below = np.flatnonzero(p_sorted <= thresholds)
    if len(below) == 0:
        return result

    k_max = int(below[-1]) + 1
    rejected_finite = np.zeros(m, dtype=bool)
    rejected_finite[order[:k_max]] = True
    result[finite_idx] = rejected_finite
    return result


def bh_adjusted_p(p_values: ArrayLike) -> np.ndarray:
    """Обчислює скориговані p-значення (q-values) за методом Бенджаміні — Хохберга."""
    p = np.asarray(p_values, dtype=float)
    if p.ndim != 1:
        raise ValueError("p_values must be a 1-D array")

    adj = np.full(p.shape, np.nan, dtype=float)
    finite_idx = np.flatnonzero(np.isfinite(p))
    m = len(finite_idx)
    if m == 0:
        return adj

    p_finite = p[finite_idx]
    order = np.argsort(p_finite, kind="mergesort")
    p_sorted = p_finite[order]

    ranks = np.arange(1, m + 1, dtype=float)
    raw_q = (m / ranks) * p_sorted
    # Монотонність справа наліво: q_(i) = min_{j >= i} (m / j * p_(j))
    q_sorted = np.minimum.accumulate(raw_q[::-1])[::-1]
    q_sorted = np.clip(q_sorted, 0.0, 1.0)

    q_finite = np.empty(m, dtype=float)
    q_finite[order] = q_sorted
    adj[finite_idx] = q_finite
    return adj


bh_fdr = benjamini_hochberg
