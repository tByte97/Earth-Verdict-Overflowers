#!/usr/bin/env python3
"""Розрахунок трендів Сена та значущості Манна — Кендалла з BH-FDR по комірках сітки.

Запуск із кореня репозиторію:
  backend/.venv/bin/python tools/build_grid_trends.py
"""
import calendar
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))

from app.check import STATS_ENGINE  # noqa: E402
from app.stats.fdr import benjamini_hochberg  # noqa: E402
from app.stats.trend import analyze_trend  # noqa: E402
from fetch_data import DATA, END, START, haversine_km  # noqa: E402

GRID_DIR = DATA / "grid"
SEASONS = ["JJA", "DJF", "year"]
SEASON_MONTHS = {
    "year": list(range(1, 13)),
    "DJF": [12, 1, 2],
    "JJA": [6, 7, 8],
}
PARAM_CONFIG = {
    "T2M": {"agg": "mean", "per_day": False, "units_per_decade": "°C/decade", "variable_id": "air_temp"},
    "PRECTOTCORR": {"agg": "sum", "per_day": True, "units_per_decade": "mm/decade", "variable_id": "precip"},
}
LAYERS_DIR = DATA / "layers"
FDR_Q = 0.05
MIN_YEARS = 15
# The tested area (Ukraine): shares, the opposite pair and the area mean are computed here only.
# Cells fetched around it are the halo: drawn so the map fades out over real data, tested as their own
# FDR family and never counted with the core.
CORE_BBOX = (44.0, 53.0, 22.0, 41.0)   # lat_min, lat_max, lon_min, lon_max


def in_core(cell: dict) -> bool:
    return CORE_BBOX[0] <= cell["lat"] <= CORE_BBOX[1] and CORE_BBOX[2] <= cell["lon"] <= CORE_BBOX[3]


def halo_rings(cells: list[dict]) -> int:
    """How many rows/columns of halo cells surround the core on its thinnest side."""
    lats = sorted({c["lat"] for c in cells})
    lons = sorted({c["lon"] for c in cells})
    core_lats = [v for v in lats if CORE_BBOX[0] <= v <= CORE_BBOX[1]]
    core_lons = [v for v in lons if CORE_BBOX[2] <= v <= CORE_BBOX[3]]
    if not core_lats or not core_lons:
        return 0
    return min(lats.index(core_lats[0]), len(lats) - 1 - lats.index(core_lats[-1]),
               lons.index(core_lons[0]), len(lons) - 1 - lons.index(core_lons[-1]))


def sig3(p: float):
    return float(f"{p:.3g}") if math.isfinite(p) else None


def aggregate_seasonal(monthly: list, season: str, agg: str, per_day: bool, y0: int = START, y1: int = END):
    """Агрегує місячний ряд (1981-01..2025-12) у річні сезонні значення, сумісно з build_cases.py."""
    start_y = y0 + 1 if season == "DJF" else y0
    months_sel = SEASON_MONTHS[season]
    years = []
    values = []
    for y in range(start_y, y1 + 1):
        vals = []
        for m in months_sel:
            yy = y - 1 if (season == "DJF" and m == 12) else y
            idx = (yy - y0) * 12 + (m - 1)
            v = monthly[idx] if 0 <= idx < len(monthly) else None
            if v is None:
                vals = None
                break
            if agg == "sum" and per_day:
                v = v * calendar.monthrange(yy, m)[1]
            vals.append(v)
        if vals is not None:
            years.append(y)
            values.append(sum(vals) if agg == "sum" else sum(vals) / len(vals))
    return np.asarray(years, dtype=float), np.asarray(values, dtype=float)


def cell_trend(years: np.ndarray, values: np.ndarray) -> tuple[float, float]:
    """(slope_per_decade, mk_p) from the same Sen / Mann-Kendall code as a point check.

    A cell with fewer than MIN_YEARS values gives NaN and is left out of the BH-FDR denominator.
    """
    tr = analyze_trend([int(y) for y in years], [float(v) for v in values], min_years=MIN_YEARS)
    if tr is None:
        return float("nan"), float("nan")
    return float(tr.sen.slope_per_decade), float(tr.mk.p)


def build_geojson(param: str, season: str, units_per_decade: str, q: float, cell_size: dict, cells_out: list[dict], raw_flags: list[bool],
                  meta: dict | None = None, halo: list[dict] | None = None) -> dict:
    dlat = float(cell_size["lat"])
    dlon = float(cell_size["lon"])
    half_lat = dlat / 2.0
    half_lon = dlon / 2.0
    features = []
    for c, sig_raw in zip(cells_out, raw_flags):
        lat = c["lat"]
        lon = c["lon"]
        x0 = round(lon - half_lon, 5)
        x1 = round(lon + half_lon, 5)
        y0 = round(lat - half_lat, 5)
        y1 = round(lat + half_lat, 5)
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [x0, y0],
                    [x1, y0],
                    [x1, y1],
                    [x0, y1],
                    [x0, y0],
                ]],
            },
            "properties": {
                "lat": lat,
                "lon": lon,
                "slope": c["slope_per_decade"],
                "slope_per_decade": c["slope_per_decade"],
                "p": c["p"],
                "significant": c["significant_fdr"],
                "significant_fdr": c["significant_fdr"],
                "significant_raw": bool(sig_raw),
            },
        })
    # Halo cells carry no polygon: the map is painted from the cell centres.
    for c in halo or []:
        features.append({"type": "Feature", "geometry": None,
                         "properties": {"lat": c["lat"], "lon": c["lon"], "slope_per_decade": c["slope_per_decade"], "p": c["p"],
                                        "significant_fdr": c["significant_fdr"], "halo": True}})
    return {
        "type": "FeatureCollection",
        "param": param,
        "season": season,
        "units_per_decade": units_per_decade,
        "q": q,
        **(meta or {}),
        "features": features,
    }


def cells_with_trends(cells: list[dict], season: str, cfg: dict):
    """Sen slope, MK p and BH-FDR flags for one family of cells."""
    slopes = np.empty(len(cells), dtype=float)
    p_vals = np.empty(len(cells), dtype=float)
    span = [math.inf, -math.inf]
    for i, cell in enumerate(cells):
        years, vals = aggregate_seasonal(cell["monthly"], season, cfg["agg"], cfg["per_day"])
        if len(years):
            span = [min(span[0], years[0]), max(span[1], years[-1])]
        slopes[i], p_vals[i] = cell_trend(years, vals)
    fdr_sig = benjamini_hochberg(p_vals, q=FDR_Q) if len(cells) else np.zeros(0, dtype=bool)
    cells_out = [
        {
            "lat": c["lat"],
            "lon": c["lon"],
            "slope_per_decade": round(float(s), 4) if math.isfinite(s) else None,
            "p": sig3(float(p)),
            "significant_fdr": bool(sf),
        }
        for c, s, p, sf in zip(cells, slopes, p_vals, fdr_sig)
    ]
    return slopes, p_vals, fdr_sig, cells_out, span


def pair_meta(cells_out: list[dict], p_vals: np.ndarray) -> dict | None:
    """Nearest pair of cells with opposite significant trends: FDR first, else raw p < q."""
    for basis in ("significant_fdr", "raw"):
        found = find_opposite_pairs(cells_out, p_vals, basis)
        if found:
            dist, a, b = found
            cell = lambda c: {"lat": c["lat"], "lon": c["lon"], "slope_per_decade": c["slope_per_decade"], "p": c["p"]}
            return {"a": cell(a), "b": cell(b), "distance_km": round(dist), "significance": "fdr" if basis == "significant_fdr" else "raw"}
    return None


def find_opposite_pairs(cells_out: list[dict], raw_p: np.ndarray, key: str = "significant_fdr"):
    """Шукає найближчу пару комірок із протилежними значущими трендами."""
    if key == "significant_fdr":
        pos = [c for c in cells_out if c["significant_fdr"] and c["slope_per_decade"] > 0]
        neg = [c for c in cells_out if c["significant_fdr"] and c["slope_per_decade"] < 0]
    else:
        pos = [c for c, p in zip(cells_out, raw_p) if p < FDR_Q and c["slope_per_decade"] > 0]
        neg = [c for c, p in zip(cells_out, raw_p) if p < FDR_Q and c["slope_per_decade"] < 0]
    if not pos or not neg:
        return None
    best = None
    for a in pos:
        for b in neg:
            d = haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
            if best is None or d < best[0]:
                best = (d, a, b)
    return best


def main():
    t_total = time.perf_counter()
    prectot_findings = {}

    for param, cfg in PARAM_CONFIG.items():
        grid_path = GRID_DIR / f"{param}.json"
        if not grid_path.exists():
            sys.exit(f"Не знайдено {grid_path}; спочатку запустіть python3 tools/fetch_grid.py")
        grid = json.loads(grid_path.read_text())
        rings = halo_rings(grid["cells"])
        cells = [c for c in grid["cells"] if in_core(c)]
        halo_cells = [c for c in grid["cells"] if not in_core(c)]
        cell_size = grid["cell_size"]

        for season in SEASONS:
            t0 = time.perf_counter()
            slopes, p_vals, fdr_sig, cells_out, span = cells_with_trends(cells, season, cfg)
            with np.errstate(invalid="ignore"):
                raw_sig = p_vals < FDR_Q          # NaN (short cell) compares False
            # The halo is its own family: its flags never change a core cell's flag or the core counts.
            halo_out = [c for c in cells_with_trends(halo_cells, season, cfg)[3] if c["slope_per_decade"] is not None]

            n_raw = int(np.sum(raw_sig))
            n_fdr = int(np.sum(fdr_sig))
            n_tested = int(np.sum(np.isfinite(p_vals)))
            out_json = {
                "param": param,
                "season": season,
                "units_per_decade": cfg["units_per_decade"],
                "q": FDR_Q,
                "n_cells": n_tested,
                "n_significant_raw": n_raw,
                "n_significant_fdr": n_fdr,
                "stats_engine": STATS_ENGINE,
                "cells": cells_out,
            }
            json_path = GRID_DIR / f"trends_{param}_{season}.json"
            json_path.write_text(json.dumps(out_json, ensure_ascii=False, separators=(",", ":")))

            meta = {"variable_id": cfg["variable_id"], "start_year": int(span[0]), "end_year": int(span[1]),
                    "n_cells": n_tested, "n_significant_fdr": n_fdr, "n_significant_raw": n_raw,
                    "stats_engine": STATS_ENGINE, "pair": pair_meta(cells_out, p_vals), "halo_cells": rings}
            geojson = build_geojson(
                param, season, cfg["units_per_decade"], FDR_Q, cell_size, cells_out, raw_sig.tolist(), meta, halo_out
            )
            geojson_path = GRID_DIR / f"trends_{param}_{season}.geojson"
            geojson_path.write_text(json.dumps(geojson, ensure_ascii=False, separators=(",", ":")))
            LAYERS_DIR.mkdir(parents=True, exist_ok=True)
            (LAYERS_DIR / geojson_path.name).write_text(geojson_path.read_text())

            dt = time.perf_counter() - t0
            mean_slope = float(np.nanmean(slopes))
            print(
                f"[{param} {season:4}] n={len(cells_out)}, raw_sig={n_raw}, fdr_sig={n_fdr}, "
                f"mean_slope={mean_slope:+.3f} {cfg['units_per_decade']}, tested={n_tested}, "
                f"json={json_path.stat().st_size / 1024:.1f} КБ, "
                f"geojson={geojson_path.stat().st_size / 1024:.1f} КБ ({dt:.2f} с)"
            )

            if param == "PRECTOTCORR":
                prectot_findings[season] = {
                    "fdr_pair": find_opposite_pairs(cells_out, p_vals, "significant_fdr"),
                    "raw_pair": find_opposite_pairs(cells_out, p_vals, "raw"),
                    "pos_fdr": sum(1 for c in cells_out if c["significant_fdr"] and c["slope_per_decade"] > 0),
                    "neg_fdr": sum(1 for c in cells_out if c["significant_fdr"] and c["slope_per_decade"] < 0),
                    "pos_raw": int(np.sum(raw_sig & (slopes > 0))),
                    "neg_raw": int(np.sum(raw_sig & (slopes < 0))),
                }

    print("\n--- Пошук пари сусідніх регіонів із протилежними значущими трендами (PRECTOTCORR) ---")
    any_fdr = False
    for season, info in prectot_findings.items():
        print(
            f"  {season:4}: FDR значущі (+{info['pos_fdr']} / -{info['neg_fdr']}), "
            f"raw p<0.05 (+{info['pos_raw']} / -{info['neg_raw']})"
        )
        if info["fdr_pair"]:
            any_fdr = True
            dist, a, b = info["fdr_pair"]
            print(
                f"    [FDR q=0.05] Пара ({dist:.0f} км): "
                f"({a['lat']}, {a['lon']}) {a['slope_per_decade']:+.2f} мм/10р (p={a['p']}) vs "
                f"({b['lat']}, {b['lon']}) {b['slope_per_decade']:+.2f} мм/10р (p={b['p']})"
            )
        elif info["raw_pair"]:
            dist, a, b = info["raw_pair"]
            print(
                f"    [FDR q=0.05] немає (усі FDR-значущі одного знаку або 0); "
                f"за необробленим p<0.05 найближча пара ({dist:.0f} км): "
                f"({a['lat']}, {a['lon']}) {a['slope_per_decade']:+.2f} мм/10р (p={a['p']}) vs "
                f"({b['lat']}, {b['lon']}) {b['slope_per_decade']:+.2f} мм/10р (p={b['p']})"
            )
        else:
            print("    Немає протилежних значущих пар (ні за FDR, ні за raw p<0.05).")
    if not any_fdr:
        print("  Висновок (FDR q=0.05): none (пар із протилежними значущими трендами після BH-FDR немає).")

    print(f"\nУсього виконано за {time.perf_counter() - t_total:.2f} с")


if __name__ == "__main__":
    main()
