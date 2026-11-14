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
