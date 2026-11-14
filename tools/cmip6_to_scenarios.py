#!/usr/bin/env python3
"""Convert data/cmip6/<city>.json into a Scenarios object matching backend/app/models.py.

Usage:
  backend/.venv/bin/python tools/cmip6_to_scenarios.py kyiv
  backend/.venv/bin/python tools/cmip6_to_scenarios.py kyiv --variable precip --season year --baseline 600.0
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CMIP6_DIR = ROOT / "data" / "cmip6"

sys.path.insert(0, str(ROOT / "backend"))
from app.scenarios import SCENARIO_LABELS, VAR_MAP  # noqa: E402,F401
from app.scenarios import cmip6_to_scenarios as _to_scenarios  # noqa: E402


def cmip6_to_scenarios(cmip6_data, variable_id="air_temp", season="JJA", baseline_value=0.0, mode="horizons"):
    """Build a dict matching backend.app.models.Scenarios from a loaded CMIP6 city JSON."""
    sc = _to_scenarios(cmip6_data, variable_id, season, mode)
    sc["baseline_value"] = round(float(baseline_value), 2 if VAR_MAP[variable_id] == "tas" else 1)
    return sc


def load_cmip6_scenarios(city_key, variable_id="air_temp", season="JJA", baseline_value=0.0, mode="horizons"):
    """Load data/cmip6/<city_key>.json and convert to a Scenarios dict."""
    path = CMIP6_DIR / f"{city_key}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return cmip6_to_scenarios(
        data,
        variable_id=variable_id,
        season=season,
        baseline_value=baseline_value,
        mode=mode,
    )


def validate_scenarios(scenarios_dict):
    """Validate against backend.app.models.Scenarios."""
    sys.path.insert(0, str(ROOT / "backend"))
    from app.models import Scenarios  # noqa: PLC0415

    return Scenarios.model_validate(scenarios_dict)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("city", help="city key in data/cmip6/<city>.json")
    ap.add_argument("--variable", default="air_temp", choices=sorted(VAR_MAP))
    ap.add_argument("--season", default="JJA", choices=["JJA", "DJF", "year"])
    ap.add_argument("--baseline", type=float, default=0.0, help="observed baseline_value (1995-2014)")
    ap.add_argument("--mode", default="horizons", choices=["horizons", "annual"])
    a = ap.parse_args()

    scen = load_cmip6_scenarios(
        a.city,
        variable_id=a.variable,
        season=a.season,
        baseline_value=a.baseline,
        mode=a.mode,
    )
    validated = validate_scenarios(scen)
    print(validated.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
