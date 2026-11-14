"""Чи однаково швидко змінюються реаналіз і станція-свідок.

Порівнювати два довірчі інтервали окремо — слабкий тест: обидва ряди бачать ту саму погоду,
їхні похибки сильно корельовані. Тому аналізуємо ряд РІЗНИЦІ «станція − реаналіз» на спільних
роках: спільна погода в ньому скорочується, лишається розходження джерел (острів тепла міста,
перенесення станції, зміна приладів, похибка моделі). Значущий тренд різниці = швидкості різні.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import math
from typing import Optional

from .trend import analyze_trend

MIN_COMMON_YEARS = 15


@dataclass(frozen=True)
class RateComparison:
    common_years: int
    main_slope_per_decade: float      # реаналіз, лише на спільних роках
    witness_slope_per_decade: float   # станція, на тих самих роках
    difference_per_decade: float      # нахил Сена ряду «станція − реаналіз»
    ci_low: float                     # 95% інтервал різниці, на 10 років
    ci_high: float
    p: float                          # Манн–Кендалл ряду різниці (з поправкою на автокореляцію)
    consistent: bool                  # True = значущої різниці швидкостей немає


def _ok(v: Optional[float]) -> bool:
    return v is not None and math.isfinite(float(v))


def compare_rates(
    years: Sequence[int],
    main_values: Sequence[Optional[float]],
    witness_years: Sequence[int],
    witness_values: Sequence[Optional[float]],
    *,
    alpha: float = 0.05,
    min_common_years: int = MIN_COMMON_YEARS,
) -> Optional[RateComparison]:
    """None, якщо спільних років із даними менше за min_common_years."""
    main = {int(y): float(v) for y, v in zip(years, main_values) if _ok(v)}
    wit = {int(y): float(v) for y, v in zip(witness_years, witness_values) if _ok(v)}
    common = sorted(set(main) & set(wit))
    if len(common) < min_common_years:
        return None

    m_vals = [main[y] for y in common]
    w_vals = [wit[y] for y in common]
    diff = [w - m for w, m in zip(w_vals, m_vals)]

    t_main = analyze_trend(common, m_vals, min_years=3)
    t_wit = analyze_trend(common, w_vals, min_years=3)
    t_diff = analyze_trend(common, diff, min_years=3)
    if t_main is None or t_wit is None or t_diff is None:
        return None

    p = float(t_diff.mk.p)
    return RateComparison(
        common_years=len(common),
        main_slope_per_decade=float(t_main.sen.slope_per_decade),
        witness_slope_per_decade=float(t_wit.sen.slope_per_decade),
        difference_per_decade=float(t_diff.sen.slope_per_decade),
        ci_low=float(t_diff.sen.ci_low_per_year * 10),
        ci_high=float(t_diff.sen.ci_high_per_year * 10),
        p=p,
        consistent=bool(p >= alpha),
    )
