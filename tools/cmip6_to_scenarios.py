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

VAR_MAP = {
    "air_temp": "tas",
    "tas": "tas",
    "precip": "pr",
    "pr": "pr",
}

SCENARIO_LABELS = {
    "ssp126": "The world cuts emissions fast",
    "ssp245": "Roughly as now",
    "ssp585": "Emissions keep growing",
}

SCENARIO_NOTE = "These are climate-model scenarios, not a forecast. Which one happens depends on what people do."


def cmip6_to_scenarios(cmip6_data, variable_id="air_temp", season="JJA", baseline_value=0.0, mode="horizons"):
    """Build a dict matching backend.app.models.Scenarios from a loaded CMIP6 city JSON."""
    cmip_var = VAR_MAP.get(variable_id)
    if not cmip_var:
        raise ValueError(f"Unsupported variable_id {variable_id!r}; expected one of {sorted(VAR_MAP)}")
    if season not in ("JJA", "DJF", "year"):
        raise ValueError(f"Unsupported season {season!r}; expected 'JJA', 'DJF', or 'year'")

    models = cmip6_data["models"]
    digits = 2 if cmip_var == "tas" else 1

    if mode == "horizons":
        years = cmip6_data["horizons"]["years"]
        block = cmip6_data["horizons"]["variables"][cmip_var][season]
    elif mode == "annual":
        years = cmip6_data["annual"]["ssp_years"]
        block = cmip6_data["annual"]["variables"][cmip_var][season]
    else:
        raise ValueError(f"Unsupported mode {mode!r}; expected 'horizons' or 'annual'")

    paths = []
    for scen_id, label in SCENARIO_LABELS.items():
        s_data = block[scen_id]
        paths.append({
            "id": scen_id,
            "label": label,
            "years": list(years),
            "median": [round(float(v), digits) for v in s_data["median"]],
            "low": [round(float(v), digits) for v in s_data["low"]],
            "high": [round(float(v), digits) for v in s_data["high"]],
        })

    return {
        "synthetic": False,
        "source": f"NASA NEX-GDDP-CMIP6 ({len(models)}-model ensemble: {', '.join(models)})",
        "baseline_period": cmip6_data["baseline_period"],
        "baseline_value": round(float(baseline_value), digits),
        "note": SCENARIO_NOTE,
        "paths": paths,
    }


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
