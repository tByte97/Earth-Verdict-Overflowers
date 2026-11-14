"""Climate-model scenarios (metric C) from precomputed NEX-GDDP-CMIP6 point files.

A full ensemble for one point takes ~80 minutes to download (tools/fetch_cmip6.py), so live checks
reuse the nearest precomputed point within SCENARIO_MAX_KM instead of fetching on request.
"""
from __future__ import annotations

import json
import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

CMIP6_DIR = Path(os.environ.get("EV_DATA_DIR", Path(__file__).resolve().parents[2] / "data")) / "cmip6"
SCENARIO_MAX_KM = 50.0

VAR_MAP = {"air_temp": "tas", "precip": "pr"}
SEASONS = ("JJA", "DJF", "year")
SCENARIO_LABELS = {
    "ssp126": "The world cuts emissions fast",
    "ssp245": "Roughly as now",
    "ssp585": "Emissions keep growing",
}
SCENARIO_NOTE = "These are climate-model scenarios, not a forecast. Which one happens depends on what people do."


def cmip6_to_scenarios(data: dict, variable_id: str = "air_temp", season: str = "JJA",
                       mode: str = "horizons") -> dict:
    """Scenarios dict (without baseline_value) from a data/cmip6/<point>.json file."""
    cmip_var = VAR_MAP.get(variable_id)
    if cmip_var is None:
        raise ValueError(f"No CMIP6 variable for {variable_id!r}")
    if season not in SEASONS:
        raise ValueError(f"No CMIP6 summary for season {season!r}")
    if mode == "horizons":
        years = data["horizons"]["years"]
        block = data["horizons"]["variables"][cmip_var][season]
    elif mode == "annual":
        years = data["annual"]["ssp_years"]
        block = data["annual"]["variables"][cmip_var][season]
    else:
        raise ValueError(f"Unsupported mode {mode!r}")
    digits = 2 if cmip_var == "tas" else 1
    win = data["horizons"].get("windows", {}) if mode == "horizons" else {}
    windows = [win.get(str(y), str(y)) for y in years]
    paths = [dict(id=sid, label=label, years=list(years), windows=windows,
                  median=[round(float(v), digits) for v in block[sid]["median"]],
                  low=[round(float(v), digits) for v in block[sid]["low"]],
                  high=[round(float(v), digits) for v in block[sid]["high"]])
             for sid, label in SCENARIO_LABELS.items()]
    models = data["models"]
    return dict(synthetic=False,
                source=f"NASA NEX-GDDP-CMIP6 ({len(models)}-model ensemble: {', '.join(models)})",
                baseline_period=data["baseline_period"], note=SCENARIO_NOTE, paths=paths)


def add_observed_context(scen: dict, years: list[int], values: list[Optional[float]],
                         decimals: int) -> dict:
    """Absolute scenario values (baseline_value + change) and, for every path and node, the
    observed year closest to the scenario median. Needs scen["baseline_value"]."""
    base = scen["baseline_value"]
    obs = [(y, v) for y, v in zip(years, values) if v is not None]
    lo = min((v for _, v in obs), default=None)
    hi = max((v for _, v in obs), default=None)
    ranked = sorted(obs, key=lambda yv: -yv[1])
    rank = {y: i + 1 for i, (y, _) in enumerate(ranked)}
    for path in scen["paths"]:
        for k in ("median", "low", "high"):
            path[f"{k}_value"] = [round(base + d, decimals) for d in path[k]]
        analogs = []
        for node, target in zip(path["years"], path["median_value"]):
            if not obs or target > hi or target < lo:
                analogs.append(dict(year=node, analog_year=None, analog_value=None, analog_rank=None,
                                    beyond_record=bool(obs)))
                continue
            # closest value; on a tie the more recent year
            y, v = min(obs, key=lambda yv: (abs(yv[1] - target), -yv[0]))
            analogs.append(dict(year=node, analog_year=y, analog_value=round(v, decimals),
                                analog_rank=rank[y], beyond_record=False))
        path["analogs"] = analogs
    return scen


def _provenance(data: dict) -> dict:
    return dict(what="Future scenarios", source="NASA NCCS",
                product=f"NEX-GDDP-CMIP6 v2.0, {len(data['models'])} models, r1i1p1f1",
                url=data.get("catalog_url", "https://ds.nccs.nasa.gov/thredds/catalog/AMES/NEX/GDDP-CMIP6/catalog.html"),
                retrieved_at=data.get("retrieved", ""), license="CC BY 4.0 (NASA NEX-GDDP-CMIP6)")


@lru_cache(maxsize=None)
def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _points() -> list[Path]:
    return sorted(CMIP6_DIR.glob("*.json")) if CMIP6_DIR.is_dir() else []


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def scenarios_for_point(key: str, variable_id: str, season) -> Optional[dict]:
    """Scenarios for a precomputed point by file key, with provenance (popped by assemble_result)."""
    path = CMIP6_DIR / f"{key}.json"
    if variable_id not in VAR_MAP or season not in SEASONS or not path.exists():
        return None
    data = _load(path)
    sc = cmip6_to_scenarios(data, variable_id, season)
    sc["provenance"] = [_provenance(data)]
    return sc


def nearby_scenarios(variable_id: str, season, lat: float, lon: float,
                     max_km: float = SCENARIO_MAX_KM) -> Optional[dict]:
    """Scenarios of the nearest precomputed point within max_km, else None."""
    if variable_id not in VAR_MAP or season not in SEASONS:
        return None
    best = None
    for path in _points():
        d = _load(path)
        km = _km(lat, lon, d["lat"], d["lon"])
        if km <= max_km and (best is None or km < best[0]):
            best = (km, path.stem)
    if best is None:
        return None
    sc = scenarios_for_point(best[1], variable_id, season)
    if sc is not None and best[0] > 5:
        sc["source"] += f"; computed for a point {best[0]:.0f} km away"
    return sc
