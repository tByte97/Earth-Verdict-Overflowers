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
import pymannkendall as pmk
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))

from app.stats.fdr import benjamini_hochberg  # noqa: E402
from fetch_data import DATA, END, START, haversine_km  # noqa: E402

GRID_DIR = DATA / "grid"
SEASONS = ["JJA", "DJF", "year"]
SEASON_MONTHS = {
    "year": list(range(1, 13)),
    "DJF": [12, 1, 2],
    "JJA": [6, 7, 8],
}
PARAM_CONFIG = {
    "T2M": {"agg": "mean", "per_day": False, "units_per_decade": "°C/decade"},
    "PRECTOTCORR": {"agg": "sum", "per_day": True, "units_per_decade": "mm/decade"},
}
FDR_Q = 0.05
MIN_YEARS = 15


def sig3(p: float) -> float:
    return float(f"{p:.3g}")


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


def cell_trend(years: np.ndarray, values: np.ndarray) -> tuple[float, float, str]:
    """Повертає (slope_per_decade, mk_p, test_used)."""
    if len(values) < MIN_YEARS:
        return float("nan"), float("nan"), "short"
    ts = stats.theilslopes(values, years, alpha=0.95)
    with np.errstate(invalid="ignore"):
        mk = pmk.hamed_rao_modification_test(values)
    used = "hamed_rao"
    if not math.isfinite(mk.p):
        mk = pmk.original_test(values)
        used = "original"
    return float(ts.slope * 10.0), float(mk.p), used


def build_geojson(param: str, season: str, units_per_decade: str, q: float, cell_size: dict, cells_out: list[dict], raw_flags: list[bool]) -> dict:
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
    return {
        "type": "FeatureCollection",
        "param": param,
        "season": season,
        "units_per_decade": units_per_decade,
        "q": q,
        "features": features,
    }


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
        cells = grid["cells"]
        cell_size = grid["cell_size"]

        for season in SEASONS:
            t0 = time.perf_counter()
            slopes = np.empty(len(cells), dtype=float)
            p_vals = np.empty(len(cells), dtype=float)
            fallbacks = 0

            for i, cell in enumerate(cells):
                years, vals = aggregate_seasonal(
                    cell["monthly"], season, cfg["agg"], cfg["per_day"]
                )
                s_dec, p, used = cell_trend(years, vals)
                slopes[i] = s_dec
                p_vals[i] = p
                if used == "original":
                    fallbacks += 1

            raw_sig = p_vals < FDR_Q
            fdr_sig = benjamini_hochberg(p_vals, q=FDR_Q)

            cells_out = [
                {
                    "lat": c["lat"],
                    "lon": c["lon"],
                    "slope_per_decade": round(float(s), 4),
                    "p": sig3(float(p)),
                    "significant_fdr": bool(sf),
                }
                for c, s, p, sf in zip(cells, slopes, p_vals, fdr_sig)
            ]

            n_raw = int(np.sum(raw_sig))
            n_fdr = int(np.sum(fdr_sig))
            out_json = {
                "param": param,
                "season": season,
                "units_per_decade": cfg["units_per_decade"],
                "q": FDR_Q,
                "n_cells": len(cells_out),
                "n_significant_raw": n_raw,
                "n_significant_fdr": n_fdr,
                "cells": cells_out,
            }
            json_path = GRID_DIR / f"trends_{param}_{season}.json"
            json_path.write_text(json.dumps(out_json, ensure_ascii=False, separators=(",", ":")))

            geojson = build_geojson(
                param, season, cfg["units_per_decade"], FDR_Q, cell_size, cells_out, raw_sig.tolist()
            )
            geojson_path = GRID_DIR / f"trends_{param}_{season}.geojson"
            geojson_path.write_text(json.dumps(geojson, ensure_ascii=False, separators=(",", ":")))

            dt = time.perf_counter() - t0
            mean_slope = float(np.nanmean(slopes))
            print(
                f"[{param} {season:4}] n={len(cells_out)}, raw_sig={n_raw}, fdr_sig={n_fdr}, "
                f"mean_slope={mean_slope:+.3f} {cfg['units_per_decade']}, fallbacks={fallbacks}, "
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
