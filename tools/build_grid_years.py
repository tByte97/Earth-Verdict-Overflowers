#!/usr/bin/env python3
"""Year-by-year maps for the globe timeline.

For every grid cell and season: each year's seasonal value minus that cell's 1991-2020 average.
The file also carries the trailing 10-year average of those anomalies and each year's rank, so the
browser only draws.
Reads data/grid/<PARAM>.json (tools/fetch_grid.py) and writes data/layers/years_<variable_id>_<season>.json.

  backend/.venv/bin/python tools/build_grid_years.py
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from build_grid_trends import GRID_DIR, LAYERS_DIR, PARAM_CONFIG, SEASONS, aggregate_seasonal, halo_rings, in_core  # noqa: E402
from fetch_data import END, START  # noqa: E402

BASELINE = (1991, 2020)
MIN_BASELINE_YEARS = 20          # a cell with a thinner baseline has no normal and stays empty
WINDOW = 10                      # years in the smoothed ("10-year average") view
UNITS = {"T2M": ("°C", 1), "PRECTOTCORR": ("mm", 0)}   # units and decimals kept per cell


def year_anomalies(cells: list[dict], season: str, agg: str, per_day: bool, digits: int,
                   y0: int = START, y1: int = END, baseline: tuple[int, int] = BASELINE) -> dict:
    """Per-year anomaly of every cell, and the area-weighted mean of the core cells (the halo only fades the map out)."""
    years = list(range(y0 + 1 if season == "DJF" else y0, y1 + 1))
    column = {y: i for i, y in enumerate(years)}
    anomaly: list[list] = [[None] * len(cells) for _ in years]
    normals: list = []
    for c, cell in enumerate(cells):
        ys, vals = aggregate_seasonal(cell["monthly"], season, agg, per_day, y0, y1)
        base = [v for y, v in zip(ys, vals) if baseline[0] <= y <= baseline[1]]
        if len(base) < MIN_BASELINE_YEARS:
            normals.append(None)
            continue
        normal = sum(base) / len(base)
        normals.append(normal)
        for y, v in zip(ys, vals):
            anomaly[column[int(y)]][c] = float(v - normal)

    # Trailing WINDOW-year average: empty until a cell has all WINDOW years.
    smooth: list[list] = [[None] * len(cells) for _ in years]
    for i in range(WINDOW - 1, len(years)):
        for c in range(len(cells)):
            span = [anomaly[k][c] for k in range(i - WINDOW + 1, i + 1)]
            if None not in span:
                smooth[i][c] = sum(span) / WINDOW

    weights = [math.cos(math.radians(cell["lat"])) if in_core(cell) else 0.0 for cell in cells]

    def area_mean(values: list):
        pairs = [(v, w) for v, w in zip(values, weights) if v is not None and w]
        return sum(v * w for v, w in pairs) / sum(w for _, w in pairs) if pairs else None

    # Means come from the unrounded cells; the per-cell values are rounded only for the file.
    rounded = lambda values: [None if m is None else round(m, 2) for m in values]
    per_cell = lambda rows: [[None if v is None else (round(v, digits) if digits else int(round(v))) for v in row] for row in rows]
    mean = rounded(area_mean(row) for row in anomaly)
    order = sorted((i for i, m in enumerate(mean) if m is not None), key=lambda i: -mean[i])
    rank = [None] * len(years)
    for place, i in enumerate(order, start=1):
        rank[i] = place                       # 1 = the highest year
    normal = area_mean(normals)
    return {"years": years,
            "anomaly": per_cell(anomaly),
            "mean": mean,
            "rank": rank,
            "window": WINDOW,
            "anomaly_smooth": per_cell(smooth),
            "mean_smooth": rounded(area_mean(row) for row in smooth),
            "normal": None if normal is None else round(normal, 2)}


def main() -> None:
    for param, cfg in PARAM_CONFIG.items():
        path = GRID_DIR / f"{param}.json"
        if not path.exists():
            sys.exit(f"{path} not found; run tools/fetch_grid.py first")
        cells = json.loads(path.read_text())["cells"]
        units, digits = UNITS[param]
        for season in SEASONS:
            out = year_anomalies(cells, season, cfg["agg"], cfg["per_day"], digits)
            layer = {"variable_id": cfg["variable_id"], "param": param, "season": season, "units": units,
                     "baseline": list(BASELINE), "start_year": out["years"][0], "end_year": out["years"][-1],
                     "source": "NASA POWER (MERRA-2)", "halo_cells": halo_rings(cells),
                     "lat": [c["lat"] for c in cells], "lon": [c["lon"] for c in cells], **out}
            target = LAYERS_DIR / f"years_{cfg['variable_id']}_{season}.json"
            target.write_text(json.dumps(layer, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"{target.name}: {len(out['years'])} years x {len(cells)} cells, {target.stat().st_size // 1024} KB, "
                  f"mean {out['mean'][0]} -> {out['mean'][-1]} {units}")


if __name__ == "__main__":
    main()
