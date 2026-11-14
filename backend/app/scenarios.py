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
    paths = [dict(id=sid, label=label, years=list(years),
                  median=[round(float(v), digits) for v in block[sid]["median"]],
                  low=[round(float(v), digits) for v in block[sid]["low"]],
                  high=[round(float(v), digits) for v in block[sid]["high"]])
             for sid, label in SCENARIO_LABELS.items()]
    models = data["models"]
    return dict(synthetic=False,
                source=f"NASA NEX-GDDP-CMIP6 ({len(models)}-model ensemble: {', '.join(models)})",
                baseline_period=data["baseline_period"], note=SCENARIO_NOTE, paths=paths)


def _provenance(data: dict) -> dict:
    return dict(what="Future scenarios", source="NASA NCCS",
                product=f"NEX-GDDP-CMIP6 v2.0, {len(data['models'])} models, r1i1p1f1",
                url=data.get("catalog_url", "https://ds.nccs.nasa.gov/thredds/catalog/AMES/NEX/GDDP-CMIP6/catalog.html"),
                retrieved_at=data.get("retrieved", ""), license="CC BY 4.0 (NASA NEX-GDDP-CMIP6)")


@lru_cache(maxsize=None)
def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _points() -> list[Path]:
    """Single-point ensembles (tools/fetch_cmip6.py): data/cmip6/<city>.json."""
    if not CMIP6_DIR.is_dir():
        return []
    return sorted(p for p in CMIP6_DIR.glob("*.json") if not p.name.startswith("region-"))


def _regions() -> list[Path]:
    """Gridded ensembles (tools/fetch_cmip6_region.py): data/cmip6/region-<name>.json."""
    return sorted(p for p in CMIP6_DIR.glob("region-*.json") if "smoke" not in p.name) if CMIP6_DIR.is_dir() else []


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


def region_scenarios(variable_id: str, season, lat: float, lon: float) -> Optional[dict]:
    """Scenarios of the grid cell that contains (lat, lon) in a precomputed region, else None.

    Region files hold, per variable/season/scenario, median/low/high arrays shaped
    [horizon][lat][lon] on the 0.25 degree NEX-GDDP grid (see data/cmip6/README.md).
    """
    if variable_id not in VAR_MAP or season not in SEASONS:
        return None
    cmip_var = VAR_MAP[variable_id]
    digits = 2 if cmip_var == "tas" else 1
    for path in _regions():
        d = _load(path)
        lats, lons = d["grid"]["lat"], d["grid"]["lon"]
        half = 0.125
        if not (min(lats) - half <= lat <= max(lats) + half and min(lons) - half <= lon <= max(lons) + half):
            continue
        i = min(range(len(lats)), key=lambda k: abs(lats[k] - lat))
        j = min(range(len(lons)), key=lambda k: abs(lons[k] - lon))
        block = d["variables"][cmip_var][season]
        n = len(d["horizons"]["years"])
        paths = []
        for sid, label in SCENARIO_LABELS.items():
            cols = {}
            for key in ("median", "low", "high"):
                vals = [block[sid][key][h][i][j] for h in range(n)]
                if any(v is None for v in vals):
                    return None          # no data in this cell (e.g. outside the model's land/sea mask)
                cols[key] = [round(float(v), digits) for v in vals]
            paths.append(dict(id=sid, label=label, years=list(d["horizons"]["years"]), **cols))
        models = d["models"]
        return dict(synthetic=False,
                    source=f"NASA NEX-GDDP-CMIP6 ({len(models)}-model ensemble: {', '.join(models)})",
                    baseline_period=d["baseline_period"], note=SCENARIO_NOTE, paths=paths,
                    provenance=[_provenance(d)])
    return None


def nearby_scenarios(variable_id: str, season, lat: float, lon: float,
                     max_km: float = SCENARIO_MAX_KM) -> Optional[dict]:
    """Scenarios for a place: its grid cell in a precomputed region, else the nearest
    precomputed point within max_km, else None."""
    if variable_id not in VAR_MAP or season not in SEASONS:
        return None
    sc = region_scenarios(variable_id, season, lat, lon)
    if sc is not None:
        return sc
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
