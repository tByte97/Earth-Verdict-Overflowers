"""Порівняння швидкостей реаналізу й станції через ряд різниці."""
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.stats.witness import compare_rates

YEARS = list(range(1981, 2026))


def _weather(seed, sd=0.9):
    return np.random.default_rng(seed).normal(0, sd, len(YEARS))


def test_same_rate_with_shared_weather_is_consistent():
    # Обидва ряди бачать ту саму погоду і однаковий тренд; станція має лише малий власний шум
    # і сталий зсув (інша висота). Швидкості мають збігтися.
    t = np.arange(len(YEARS))
    w = _weather(1)
    main = 19 + 0.06 * t + w
    station = 19.8 + 0.06 * t + w + np.random.default_rng(2).normal(0, 0.15, len(YEARS))
    r = compare_rates(YEARS, list(main), YEARS, list(station))
    assert r is not None and r.common_years == 45
    assert r.consistent
    assert abs(r.difference_per_decade) < 0.1


def test_station_warming_faster_is_detected():
    # Острів тепла міста: станція гріється на 0.02 °C/рік швидше. Окремі CI двох рядів
    # перетиналися б, а тест різниці бачить розходження, бо спільна погода скорочується.
    t = np.arange(len(YEARS))
    w = _weather(3)
    main = 19 + 0.06 * t + w
    station = 19 + 0.08 * t + w + np.random.default_rng(4).normal(0, 0.15, len(YEARS))
    r = compare_rates(YEARS, list(main), YEARS, list(station))
    assert r is not None
    assert not r.consistent and r.p < 0.05
    assert 0.1 < r.difference_per_decade < 0.3
    assert r.witness_slope_per_decade > r.main_slope_per_decade


def test_uses_only_common_years_and_gaps():
    t = np.arange(len(YEARS))
    w = _weather(5)
    main = list(19 + 0.05 * t + w)
    station = [None if 2006 <= y <= 2021 else v for y, v in zip(YEARS, 19 + 0.05 * t + w)]
    r = compare_rates(YEARS, main, YEARS, station)
    assert r is not None and r.common_years == 45 - 16


def test_too_few_common_years_returns_none():
    main = [float(i) for i in range(len(YEARS))]
    station = [None] * 35 + [float(i) for i in range(10)]
    assert compare_rates(YEARS, main, YEARS, station) is None
