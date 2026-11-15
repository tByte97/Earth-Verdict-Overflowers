#!/usr/bin/env python3
"""Завантаження регіональної сітки NASA POWER (MERRA-2) для карти трендів Earth Verdict.

Використовує кеш із tools/fetch_data.py (get_json -> data/cache/).
Запуск із кореня репозиторію:
  python3 tools/fetch_grid.py
"""
import argparse
import json
import time
from pathlib import Path

from fetch_data import DATA, END, START, get_json, months

REGIONAL_URL = "https://power.larc.nasa.gov/api/temporal/monthly/regional"
GRID_DIR = DATA / "grid"
DEFAULT_PARAMS = ["T2M", "PRECTOTCORR"]
DEFAULT_BBOX = (40, 56.5, 16, 46.5)  # lat_min, lat_max, lon_min, lon_max (Ukraine + fade halo)
MAX_SPAN = 10.0
MIN_SPAN = 2.0


def _clean_coord(val: float):
    return int(val) if float(val).is_integer() else round(float(val), 4)


def tile_axis(lo: float, hi: float, max_span: float = MAX_SPAN) -> list[tuple]:
    """Розбиває відрізок [lo, hi] на підвідрізки довжиною <= max_span (і >= 2° для API)."""
    if hi - lo <= max_span:
        return [(_clean_coord(lo), _clean_coord(hi))]
    segments = []
    cur = lo
    while cur < hi - 1e-9:
        nxt = min(cur + max_span, hi)
        seg_lo = cur
        if nxt - seg_lo < MIN_SPAN and hi - lo >= MIN_SPAN:
            seg_lo = max(lo, nxt - MIN_SPAN)
        segments.append((_clean_coord(seg_lo), _clean_coord(nxt)))
        cur = nxt
    return segments


def tile_bbox(lat_min: float, lat_max: float, lon_min: float, lon_max: float) -> list[tuple]:
    """Розбиває прямокутник на тайли <= 10°×10°."""
    lat_tiles = tile_axis(lat_min, lat_max)
    lon_tiles = tile_axis(lon_min, lon_max)
    return [
        (la0, la1, lo0, lo1)
        for la0, la1 in lat_tiles
        for lo0, lo1 in lon_tiles
    ]


def verify_cell_size(cells: list[dict]) -> dict[str, float]:
    """Перевіряє крок сітки за широтою та довготою."""
    lats = sorted({c["lat"] for c in cells})
    lons = sorted({c["lon"] for c in cells})
    dlats = {round(b - a, 6) for a, b in zip(lats, lats[1:])}
    dlons = {round(b - a, 6) for a, b in zip(lons, lons[1:])}
    if len(dlats) != 1 or len(dlons) != 1:
        raise ValueError(f"Нерівномірна сітка: dlat={dlats}, dlon={dlons}")
    dlat = dlats.pop()
    dlon = dlons.pop()
    return {"lat": dlat, "lon": dlon}


def fetch_param_grid(
    param: str,
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
    refresh: bool = False,
) -> dict:
    tiles = tile_bbox(lat_min, lat_max, lon_min, lon_max)
    ym_keys = [m.replace("-", "") for m in months()]
    by_coord: dict[tuple[float, float], list] = {}
    units = None

    for idx, (la0, la1, lo0, lo1) in enumerate(tiles, 1):
        t0 = time.perf_counter()
        resp = get_json(
            REGIONAL_URL,
            {
                "parameters": param,
                "community": "AG",
                "latitude-min": la0,
                "latitude-max": la1,
                "longitude-min": lo0,
                "longitude-max": lo1,
                "start": START,
                "end": END,
                "format": "JSON",
            },
            refresh=refresh,
        )
        dt = time.perf_counter() - t0
        if units is None:
            units = resp.get("parameters", {}).get(param, {}).get("units", "")
        feats = resp.get("features", [])
        for feat in feats:
            lon, lat = feat["geometry"]["coordinates"][:2]
            lat_f, lon_f = round(float(lat), 4), round(float(lon), 4)
            raw = feat["properties"]["parameter"][param]
            # Лише 12 календарних місяців на рік (YYYY01..YYYY12), ключ YYYY13 (річне) ігнорується
            series = [
                None if raw.get(k, -999) <= -900 else round(float(raw[k]), 2)
                for k in ym_keys
            ]
            by_coord[(lat_f, lon_f)] = series
        print(
            f"  [{param}] тайл {idx}/{len(tiles)} "
            f"lat={la0}..{la1} lon={lo0}..{lo1}: {len(feats)} комірок за {dt:.2f} с"
        )

    cells = [
        {"lat": lat, "lon": lon, "monthly": by_coord[(lat, lon)]}
        for (lat, lon) in sorted(by_coord)
    ]
    cell_size = verify_cell_size(cells)
    return {
        "param": param,
        "units": units,
        "cell_size": cell_size,
        "cells": cells,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--params", nargs="+", default=DEFAULT_PARAMS)
    ap.add_argument("--lat-min", type=float, default=DEFAULT_BBOX[0])
    ap.add_argument("--lat-max", type=float, default=DEFAULT_BBOX[1])
    ap.add_argument("--lon-min", type=float, default=DEFAULT_BBOX[2])
    ap.add_argument("--lon-max", type=float, default=DEFAULT_BBOX[3])
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    GRID_DIR.mkdir(parents=True, exist_ok=True)
    t_start = time.perf_counter()
    for param in args.params:
        t0 = time.perf_counter()
        data = fetch_param_grid(
            param, args.lat_min, args.lat_max, args.lon_min, args.lon_max, refresh=args.refresh
        )
        out_path = GRID_DIR / f"{param}.json"
        out_path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
        dt = time.perf_counter() - t0
        size_kb = out_path.stat().st_size / 1024
        cs = data["cell_size"]
        print(
            f"Збережено {out_path.relative_to(DATA.parent)}: "
            f"{len(data['cells'])} комірок, крок {cs['lat']}°×{cs['lon']}°, "
            f"{size_kb:.1f} КБ ({dt:.2f} с)"
        )
    print(f"Усього за {time.perf_counter() - t_start:.2f} с")


if __name__ == "__main__":
    main()
