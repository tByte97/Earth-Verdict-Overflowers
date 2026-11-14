"""Contract validation tests for generated showcase JSON cases."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.models import CheckResult
from app.verdict import sig3

CASES_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "cases"


def test_all_case_files_validate_against_check_result():
    case_files = sorted(CASES_DIR.glob("*.json"))
    expected = {
        "kyiv-summer-heat.json",
        "kyiv-winter-snow.json",
        "lviv-drier.json",
        "mock.json",
    }
    assert expected.issubset({p.name for p in case_files})

    for path in case_files:
        payload = json.loads(path.read_text())
        model = CheckResult.model_validate(payload)
        history = model.detection_history
        assert history is not None
        assert history.start_year == model.case.start_year
        assert history.points[-1].end_year == model.case.end_year
        assert history.points[-1].n_observations == model.detection.n_years
        assert sig3(history.points[-1].p) == model.mk.p
        assert model.meta.stats_engine == "backend.app.stats v2"
        if model.verdict == "not_proven":
            assert model.years_to_wait is None or model.years_to_wait >= 1
        else:
            assert model.years_to_wait is None

        # Slider and verdict agree: wait = years_needed[x1] - n_years
        det = model.detection
        needed = det.years_needed[det.multipliers.index(1.0)]
        if model.years_to_wait is not None:
            assert needed is not None and model.years_to_wait == int(needed) - det.n_years
