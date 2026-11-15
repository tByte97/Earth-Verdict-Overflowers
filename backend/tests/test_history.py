"""Prefix results use the production method without introducing future observations."""
from copy import deepcopy
from pathlib import Path
import sys

import numpy as np
import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.models import DetectionHistory
from app.stats.history import detection_history
from app.stats.trend import analyze_trend


def history(years, values):
    return detection_history(years, values, alpha=0.05, min_observations=15)


def test_prefixes_match_production_statistics_and_count_valid_observations():
    years = list(range(1981, 2012))
    values = (np.random.default_rng(42).normal(size=len(years)) + np.arange(len(years)) * 0.1).tolist()
    values[4] = values[8] = None
    result = history(years, values)
    DetectionHistory.model_validate(result)
    for i, point in enumerate(result['points']):
        assert point['n_observations'] == sum(v is not None for v in values[:i + 1])
        expected = analyze_trend(years[:i + 1], values[:i + 1], min_years=15, start_year=1981)
        if expected is None:
            assert point['p'] is None and point['status'] == 'short_series'
        else:
            assert point['p'] == expected.mk.p
            assert point['correction'] == expected.mk.correction
    assert result['points'][15]['p'] is None   # 16 calendar years, only 14 observations
    assert result['points'][16]['p'] is not None


def test_later_observations_cannot_change_an_earlier_prefix():
    years = list(range(1981, 2012))
    values = np.random.default_rng(9).normal(size=len(years)).tolist()
    before = history(years, values)
    values[-5:] = [1000, -1000, 500, -500, 0]
    after = history(years, values)
    assert before['points'][:-5] == after['points'][:-5]
    # A noisy series is allowed to cross the threshold in either direction.
    ps = [point['p'] for point in before['points'] if point['p'] is not None]
    assert any(right > left for left, right in zip(ps, ps[1:]))


def test_calendar_gaps_are_not_compressed_and_constant_values_are_not_missing():
    years = [year for year in range(2000, 2020) if year != 2005]
    result = history(years, [0.0] * len(years))
    assert len(result['points']) == 20
    assert result['points'][5]['n_observations'] == result['points'][4]['n_observations']
    assert result['points'][-1]['p'] == 1.0
    assert result['points'][-1]['n_observations'] == 19


def expected_emergence(years, values, result):
    """Brute force: the earliest end year whose every later prefix is significant with the final sign."""
    def sign(i):
        trend = analyze_trend(years[:i + 1], values[:i + 1], min_years=15, start_year=years[0])
        if trend is None or trend.mk.p >= 0.05:
            return 0
        return (trend.sen.slope_per_year > 0) - (trend.sen.slope_per_year < 0)
    signs = [sign(i) for i in range(len(years))]
    for i in range(len(years)):
        if signs[-1] and all(s == signs[-1] for s in signs[i:]):
            return result['points'][i]['end_year']
    return None


def test_emerged_year_for_a_steady_trend():
    years = list(range(1981, 2026))
    values = (np.random.default_rng(1).normal(size=len(years)) * 0.5 + np.arange(len(years)) * 0.08).tolist()
    result = history(years, values)
    assert result['emerged_year'] is not None
    assert result['emerged_year'] == expected_emergence(years, values, result)
    DetectionHistory.model_validate(result)
    later = [point for point in result['points'] if point['end_year'] >= result['emerged_year']]
    assert all(point['p'] < 0.05 for point in later)
    before = result['points'][result['emerged_year'] - years[0] - 1]
    assert before['p'] is None or before['p'] >= 0.05


def test_emerged_year_is_null_without_a_significant_full_record():
    years = list(range(1981, 2026))
    values = np.random.default_rng(3).normal(size=len(years)).tolist()
    result = history(years, values)
    assert result['points'][-1]['p'] >= 0.05
    assert result['emerged_year'] is None
    assert history(years[:10], values[:10])['emerged_year'] is None   # never enough observations


def test_emerged_year_ignores_significance_with_the_opposite_sign():
    years = list(range(1981, 2026))
    rng = np.random.default_rng(0)
    values = (np.arange(45) * -0.1 + rng.normal(size=45) * 0.5).tolist()
    values[:18] = (np.arange(18) * 0.4 + rng.normal(size=18) * 0.3).tolist()   # an early rise
    result = history(years, values)
    early = analyze_trend(years[:18], values[:18], min_years=15, start_year=1981)
    full = analyze_trend(years, values, min_years=15, start_year=1981)
    assert early.mk.p < 0.05 and early.sen.slope_per_year > 0
    assert full.mk.p < 0.05 and full.sen.slope_per_year < 0
    assert result['emerged_year'] == expected_emergence(years, values, result)
    assert result['emerged_year'] > 2005


def test_contract_accepts_old_history_and_rejects_false_emergence():
    payload = history(list(range(2000, 2020)), list(range(20)))
    old = {k: v for k, v in payload.items() if k != 'emerged_year'}
    assert DetectionHistory.model_validate(old).emerged_year is None
    for year in (2005, 1999, 2020):   # short-series prefix, before and after the record
        with pytest.raises(ValidationError):
            DetectionHistory.model_validate({**payload, 'emerged_year': year})


@pytest.mark.parametrize('change', ['order', 'count', 'p', 'status', 'correction'])
def test_contract_rejects_inconsistent_history(change):
    payload = history(list(range(2000, 2020)), list(range(20)))
    payload = deepcopy(payload)
    if change == 'order': payload['points'].reverse()
    if change == 'count': payload['points'][5]['n_observations'] = 20
    if change == 'p': payload['points'][-1]['p'] = 1.1
    if change == 'status': payload['points'][0]['status'] = 'ok'
    if change == 'correction': payload['points'][-1]['correction'] = None
    with pytest.raises(ValidationError):
        DetectionHistory.model_validate(payload)
