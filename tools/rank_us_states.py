#!/usr/bin/env python3
"""Fetch NASA POWER regional monthly grids for the US, compute per-cell trends with BH-FDR,
assign cells to US states by cell centre, and rank states by trend clarity.

Run from the repository root:
  "/Users/msushchuk/Dev/noosphere/NASA/Earth verdict/backend/.venv/bin/python" tools/rank_us_states.py
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import gzip
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))

from app.stats.fdr import benjamini_hochberg, bh_adjusted_p  # noqa: E402
from build_grid_trends import FDR_Q, SEASONS, aggregate_seasonal, cell_trend  # noqa: E402
from fetch_data import DATA, END, START, get_json, months  # noqa: E402
from fetch_grid import REGIONAL_URL, tile_bbox, verify_cell_size  # noqa: E402

SCRATCH_DIR = DATA / "us-ranking"
EXP_DIR = ROOT / "tools" / "experiments" / "us_states"

# US Census Bureau Cartographic Boundary Files (cb_2018_us_state_20m), public domain (17 U.S.C. 105)
STATES_GEOJSON_URL = (
    "https://raw.githubusercontent.com/loganpowell/census-geojson/master/GeoJSON/20m/2018/state.json"
)

DOMAINS = {
    "lower48": (24.0, 50.0, -125.0, -66.0),
    "alaska": (51.0, 71.5, -170.0, -130.0),
}

PARAM_SPECS = {
    "T2M": {"agg": "mean", "per_day": False, "units_per_decade": "°C/decade"},
    "PRECTOTCORR": {"agg": "sum", "per_day": True, "units_per_decade": "mm/decade"},
    "SNODP": {"agg": "mean", "per_day": False, "units_per_decade": "cm/decade"},
}

MIN_STATE_CELLS = 4
MAX_WORKERS = 3


def point_in_ring(lon: float, lat: float, ring: Sequence[Sequence[float]]) -> bool:
    """Ray-casting (even-odd rule) test for a single point (lon, lat) in a closed polygon ring."""
    n = len(ring)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = float(ring[i][0]), float(ring[i][1])
        xj, yj = float(ring[j][0]), float(ring[j][1])
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def point_in_polygon(lon: float, lat: float, geometry: dict[str, Any]) -> bool:
    """Return True if (lon, lat) lies inside a GeoJSON Polygon or MultiPolygon geometry."""
    gtype = geometry.get("type")
    coords = geometry.get("coordinates", [])
    if gtype == "Polygon":
        polygons = [coords]
    elif gtype == "MultiPolygon":
        polygons = coords
    else:
        return False

    for poly in polygons:
        if not poly:
            continue
        exterior = poly[0]
        if point_in_ring(lon, lat, exterior):
            if not any(point_in_ring(lon, lat, hole) for hole in poly[1:]):
                return True
    return False


def _points_in_ring_vec(lons: np.ndarray, lats: np.ndarray, ring: Sequence[Sequence[float]]) -> np.ndarray:
    """Vectorized ray-casting test for 1-D arrays of lons and lats against a single linear ring."""
    pts = np.asarray(ring, dtype=float)
    if len(pts) < 3:
        return np.zeros(len(lons), dtype=bool)
    x0, y0 = pts[:, 0], pts[:, 1]
    x1, y1 = np.roll(x0, -1), np.roll(y0, -1)

    min_x, max_x = float(np.min(x0)), float(np.max(x0))
    min_y, max_y = float(np.min(y0)), float(np.max(y0))
    in_bbox = (lons >= min_x) & (lons <= max_x) & (lats >= min_y) & (lats <= max_y)
    out = np.zeros(len(lons), dtype=bool)
    idx = np.flatnonzero(in_bbox)
    if len(idx) == 0:
        return out

    sub_lons = lons[idx]
    sub_lats = lats[idx]
    cond_y = (y0[:, None] > sub_lats[None, :]) != (y1[:, None] > sub_lats[None, :])
    dy = np.where(y1 != y0, y1 - y0, 1.0)
    x_int = (x1 - x0)[:, None] * (sub_lats[None, :] - y0[:, None]) / dy[:, None] + x0[:, None]
    crossings = cond_y & (sub_lons[None, :] < x_int)
    out[idx] = (np.count_nonzero(crossings, axis=0) % 2) == 1
    return out


def assign_cells_to_states(
    cells: Sequence[dict[str, Any]],
    geojson: dict[str, Any],
) -> tuple[list[str | None], dict[str, str]]:
    """Assign each cell {'lat': ..., 'lon': ...} to a state code by cell centre.

    Returns (assignments, state_names) where assignments[i] is the 2-letter postal code
    (or None if the cell centre falls outside all state polygons) and state_names maps
    each 2-letter code to its full English name.
    """
    lons = np.array([float(c["lon"]) for c in cells], dtype=float)
    lats = np.array([float(c["lat"]) for c in cells], dtype=float)
    assigned: list[str | None] = [None] * len(cells)
    state_names: dict[str, str] = {}

    features = sorted(
        geojson.get("features", []),
        key=lambda f: f.get("properties", {}).get("STUSPS") or f.get("properties", {}).get("NAME", ""),
    )

    for feat in features:
        props = feat.get("properties", {})
        code = props.get("STUSPS") or props.get("STATE") or props.get("NAME")
        name = props.get("NAME") or str(code)
        if not code:
            continue
        state_names[str(code)] = str(name)

        geom = feat.get("geometry", {})
        gtype = geom.get("type")
        coords = geom.get("coordinates", [])
        polygons = [coords] if gtype == "Polygon" else (coords if gtype == "MultiPolygon" else [])

        in_state = np.zeros(len(cells), dtype=bool)
        for poly in polygons:
            if not poly:
                continue
            in_poly = _points_in_ring_vec(lons, lats, poly[0])
            for hole in poly[1:]:
                if np.any(in_poly):
                    in_poly &= ~_points_in_ring_vec(lons, lats, hole)
            in_state |= in_poly

        for idx in np.flatnonzero(in_state):
            if assigned[idx] is None:
                assigned[idx] = str(code)

    return assigned, state_names


def aggregate_state_metrics(
    cell_records: Sequence[dict[str, Any]],
    state_names: dict[str, str],
    min_cells: int = MIN_STATE_CELLS,
) -> list[dict[str, Any]]:
    """Aggregate cell-level trend results per (state, param, season).

    Each item in `cell_records` must have keys:
      state, param, season, slope_per_decade, p, significant_fdr
    States with fewer than `min_cells` cells (in a given param/season) are excluded.
    """
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for rec in cell_records:
        st = rec.get("state")
        if not st:
            continue
        key = (str(st), str(rec["param"]), str(rec["season"]))
        grouped.setdefault(key, []).append(rec)

    rows: list[dict[str, Any]] = []
    for (state, param, season), items in sorted(grouped.items()):
        n_cells = len(items)
        if n_cells < min_cells:
            continue
        all_slopes = np.array([float(x["slope_per_decade"]) for x in items], dtype=float)
        sig_items = [x for x in items if bool(x["significant_fdr"])]
        n_sig = len(sig_items)
        share_sig = n_sig / n_cells
        median_all = float(np.nanmedian(all_slopes))

        if n_sig > 0:
            sig_slopes = np.array([float(x["slope_per_decade"]) for x in sig_items], dtype=float)
            median_sig: float | None = float(np.nanmedian(sig_slopes))
            n_pos = int(np.sum(sig_slopes > 0.0))
            n_neg = int(np.sum(sig_slopes < 0.0))
            consistency = max(n_pos, n_neg) / n_sig
            dominant_sign = "+" if n_pos >= n_neg else "-"
        else:
            median_sig = None
            n_pos = 0
            n_neg = 0
            consistency = 0.0
            dominant_sign = "none"

        clarity_score = share_sig * consistency
        rows.append(
            {
                "state": state,
                "state_name": state_names.get(state, state),
                "param": param,
                "season": season,
                "n_cells": n_cells,
                "n_sig_fdr": n_sig,
                "share_sig_fdr": round(share_sig, 6),
                "median_slope_sig": round(median_sig, 4) if median_sig is not None else None,
                "median_slope_all": round(median_all, 4),
                "n_sig_pos": n_pos,
                "n_sig_neg": n_neg,
                "dominant_sign": dominant_sign,
                "consistency": round(consistency, 6),
                "clarity_score": round(clarity_score, 6),
            }
        )
    return rows


def rank_temperature_states(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compute overall temperature (T2M) ranking across JJA, DJF, and year per state."""
    by_state: dict[str, dict[str, dict[str, Any]]] = {}
    for r in rows:
        if r["param"] == "T2M":
            by_state.setdefault(r["state"], {})[r["season"]] = r

    summary: list[dict[str, Any]] = []
    for state, s_map in by_state.items():
        if not s_map:
            continue
        sample = next(iter(s_map.values()))
        c_jja = float(s_map.get("JJA", {}).get("clarity_score", 0.0))
        c_djf = float(s_map.get("DJF", {}).get("clarity_score", 0.0))
        c_year = float(s_map.get("year", {}).get("clarity_score", 0.0))
        mean_clarity = (c_jja + c_djf + c_year) / 3.0
        sum_clarity = c_jja + c_djf + c_year
        summary.append(
            {
                "state": state,
                "state_name": sample["state_name"],
                "n_cells": sample["n_cells"],
                "clarity_JJA": round(c_jja, 4),
                "clarity_DJF": round(c_djf, 4),
                "clarity_year": round(c_year, 4),
                "slope_all_JJA": s_map.get("JJA", {}).get("median_slope_all"),
                "slope_all_DJF": s_map.get("DJF", {}).get("median_slope_all"),
                "slope_all_year": s_map.get("year", {}).get("median_slope_all"),
                "slope_sig_JJA": s_map.get("JJA", {}).get("median_slope_sig"),
                "slope_sig_DJF": s_map.get("DJF", {}).get("median_slope_sig"),
                "slope_sig_year": s_map.get("year", {}).get("median_slope_sig"),
                "mean_clarity": round(mean_clarity, 6),
                "sum_clarity": round(sum_clarity, 6),
            }
        )
    summary.sort(
        key=lambda x: (
            -x["mean_clarity"],
            -x["clarity_year"],
            -x["clarity_JJA"],
            -(x["slope_all_year"] or -999.0),
            x["state"],
        )
    )
    return summary


def cmip6_box_cell_count(south: float, west: float, north: float, east: float, step: float = 0.25) -> tuple[int, int, int]:
    """Return (n_lat, n_lon, total_cells) for a CMIP6 0.25-deg regional box (inclusive endpoints)."""
    n_lat = int(round((north - south) / step)) + 1
    n_lon = int(round((east - west) / step)) + 1
    return n_lat, n_lon, n_lat * n_lon


def _fetch_single_tile(
    param: str,
    domain_name: str,
    idx: int,
    total_tiles: int,
    bbox: tuple[float, float, float, float],
    refresh: bool,
) -> tuple[str, int, tuple[float, float, float, float], dict[str, Any] | None, str | None, float]:
    la0, la1, lo0, lo1 = bbox
    t0 = time.perf_counter()
    try:
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
            retries=4,
        )
        dt = time.perf_counter() - t0
        return domain_name, idx, bbox, resp, None, dt
    except Exception as exc:
        dt = time.perf_counter() - t0
        return domain_name, idx, bbox, None, str(exc), dt


def fetch_us_param_grid(
    param: str,
    refresh: bool = False,
    max_workers: int = MAX_WORKERS,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Fetch Lower 48 and Alaska tiles for `param` using data/cache and save assembled grid."""
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    grid_cache_path = SCRATCH_DIR / f"grid_us_{param}.json"
    if grid_cache_path.exists() and not refresh:
        cached = json.loads(grid_cache_path.read_text(encoding="utf-8"))
        return cached, cached.get("failed_tiles", [])

    ym_keys = [m.replace("-", "") for m in months()]
    by_coord: dict[tuple[float, float], list[float | None]] = {}
    by_domain_coords: dict[str, list[dict[str, float]]] = {k: [] for k in DOMAINS}
    units = None
    failed_tiles: list[dict[str, Any]] = []

    jobs: list[tuple[str, int, int, tuple[float, float, float, float]]] = []
    for dname, (la_min, la_max, lo_min, lo_max) in DOMAINS.items():
        tiles = tile_bbox(la_min, la_max, lo_min, lo_max)
        for i, tb in enumerate(tiles, 1):
            jobs.append((dname, i, len(tiles), tb))

    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, 3))) as pool:
        futures = [
            pool.submit(_fetch_single_tile, param, dname, i, n_t, tb, refresh)
            for (dname, i, n_t, tb) in jobs
        ]
        for fut in as_completed(futures):
            dname, idx, (la0, la1, lo0, lo1), resp, err, dt = fut.result()
            if err is not None or resp is None:
                failed_tiles.append(
                    {
                        "param": param,
                        "domain": dname,
                        "tile_index": idx,
                        "bbox": [la0, la1, lo0, lo1],
                        "error": err,
                    }
                )
                print(
                    f"  [{param}] FAILED {dname} tile #{idx} lat={la0}..{la1} lon={lo0}..{lo1}: {err}",
                    file=sys.stderr,
                )
                continue

            if units is None:
                units = resp.get("parameters", {}).get(param, {}).get("units", "")
            feats = resp.get("features", [])
            for feat in feats:
                lon, lat = feat["geometry"]["coordinates"][:2]
                lat_f, lon_f = round(float(lat), 4), round(float(lon), 4)
                raw = feat["properties"]["parameter"][param]
                series = [
                    None if raw.get(k, -999) <= -900 else round(float(raw[k]), 2)
                    for k in ym_keys
                ]
                by_coord[(lat_f, lon_f)] = series
                by_domain_coords[dname].append({"lat": lat_f, "lon": lon_f})
            print(
                f"  [{param}] {dname} tile #{idx} lat={la0}..{la1} lon={lo0}..{lo1}: "
                f"{len(feats)} cells in {dt:.2f}s"
            )

    if not by_coord:
        return None, failed_tiles

    cell_sizes = {}
    for dname, dcoords in by_domain_coords.items():
        if dcoords:
            cell_sizes[dname] = verify_cell_size(dcoords)

    cells = [
        {"lat": lat, "lon": lon, "monthly": by_coord[(lat, lon)]}
        for (lat, lon) in sorted(by_coord)
    ]
    out = {
        "param": param,
        "units": units,
        "cell_sizes": cell_sizes,
        "failed_tiles": failed_tiles,
        "cells": cells,
    }
    grid_cache_path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return out, failed_tiles


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--params", nargs="+", default=list(PARAM_SPECS.keys()))
    ap.add_argument("--refresh", action="store_true", help="Ignore cached grid and API responses")
    ap.add_argument("--workers", type=int, default=MAX_WORKERS, help="Concurrent tile requests (<=3)")
    args = ap.parse_args()

    t_start = time.perf_counter()
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    EXP_DIR.mkdir(parents=True, exist_ok=True)

    print("1. Loading US state boundaries GeoJSON ...")
    states_gj = get_json(STATES_GEOJSON_URL, {}, refresh=args.refresh)
    print(f"   Loaded {len(states_gj.get('features', []))} state/territory features.")

    all_failed_tiles: list[dict[str, Any]] = []
    grids: dict[str, dict[str, Any]] = {}
    ref_Source_cells: list[dict[str, Any]] | None = None

    print("2. Fetching NASA POWER regional monthly grids (1981-2025) ...")
    for param in args.params:
        if param not in PARAM_SPECS:
            raise ValueError(f"Unsupported parameter: {param}")
        grid, failed = fetch_us_param_grid(param, refresh=args.refresh, max_workers=args.workers)
        all_failed_tiles.extend(failed)
        if grid is None:
            print(f"   [{param}] Skipped (endpoint refused or returned no cells).")
            continue
        grids[param] = grid
        if ref_Source_cells is None:
            ref_Source_cells = [{"lat": c["lat"], "lon": c["lon"]} for c in grid["cells"]]
        print(f"   [{param}] Ready: {len(grid['cells'])} total grid cells across Lower 48 + Alaska.")

    if not ref_Source_cells:
        sys.exit("No parameter grids could be fetched.")

    print("3. Assigning grid cells to US states by cell centre ...")
    t_pip = time.perf_counter()
    assignments, state_names = assign_cells_to_states(ref_Source_cells, states_gj)
    coord_to_state = {
        (c["lat"], c["lon"]): st for c, st in zip(ref_Source_cells, assignments)
    }

    state_cell_counts: dict[str, int] = {}
    for st in assignments:
        if st is not None:
            state_cell_counts[st] = state_cell_counts.get(st, 0) + 1

    dropped_states = {st: cnt for st, cnt in sorted(state_cell_counts.items()) if cnt < MIN_STATE_CELLS}
    kept_states = {st: cnt for st, cnt in sorted(state_cell_counts.items()) if cnt >= MIN_STATE_CELLS}
    print(
        f"   Assigned {sum(state_cell_counts.values())}/{len(ref_Source_cells)} cells to "
        f"{len(state_cell_counts)} states in {time.perf_counter() - t_pip:.2f}s."
    )
    print(f"   Kept {len(kept_states)} states (>= {MIN_STATE_CELLS} cells); dropped (< {MIN_STATE_CELLS} cells): {dropped_states}")

    print("4. Computing per-cell seasonal trends and US-wide BH-FDR (q=0.05) ...")
    all_cell_records: list[dict[str, Any]] = []
    fdr_summary: list[dict[str, Any]] = []

    for param, grid in grids.items():
        spec = PARAM_SPECS[param]
        # Keep only cells whose centre falls inside a US state polygon
        us_cells = [
            (c, coord_to_state.get((c["lat"], c["lon"])))
            for c in grid["cells"]
            if coord_to_state.get((c["lat"], c["lon"])) is not None
        ]
        for season in SEASONS:
            t0 = time.perf_counter()
            slopes = np.empty(len(us_cells), dtype=float)
            p_vals = np.empty(len(us_cells), dtype=float)
            fallbacks = 0

            for i, (cell, _st) in enumerate(us_cells):
                years, vals = aggregate_seasonal(
                    cell["monthly"], season, spec["agg"], spec["per_day"], y0=START, y1=END
                )
                s_dec, p, used = cell_trend(years, vals)
                slopes[i] = s_dec
                p_vals[i] = p
                if used == "original":
                    fallbacks += 1

            raw_sig = p_vals < FDR_Q
            fdr_sig = benjamini_hochberg(p_vals, q=FDR_Q)
            q_vals = bh_adjusted_p(p_vals)

            for (cell, st), s_dec, p_val, q_val, is_raw, is_fdr in zip(
                us_cells, slopes, p_vals, q_vals, raw_sig, fdr_sig
            ):
                all_cell_records.append(
                    {
                        "state": st,
                        "lat": cell["lat"],
                        "lon": cell["lon"],
                        "param": param,
                        "season": season,
                        "slope_per_decade": round(float(s_dec), 4) if math.isfinite(s_dec) else float("nan"),
                        "p": float(f"{p_val:.4g}") if math.isfinite(p_val) else float("nan"),
                        "q": float(f"{q_val:.4g}") if math.isfinite(q_val) else float("nan"),
                        "significant_raw": int(bool(is_raw)),
                        "significant_fdr": int(bool(is_fdr)),
                    }
                )

            dt = time.perf_counter() - t0
            n_raw = int(np.sum(raw_sig))
            n_fdr = int(np.sum(fdr_sig))
            fdr_summary.append(
                {
                    "param": param,
                    "season": season,
                    "m_us_cells": len(us_cells),
                    "n_sig_raw": n_raw,
                    "n_sig_fdr": n_fdr,
                    "fallbacks": fallbacks,
                    "seconds": round(dt, 2),
                }
            )
            print(
                f"   [{param:11} {season:4}] m={len(us_cells)} US cells, "
                f"raw_sig={n_raw}, fdr_sig={n_fdr} ({100.0 * n_fdr / len(us_cells):.1f}%), "
                f"fallbacks={fallbacks} ({dt:.2f}s)"
            )

    print("5. Aggregating per-state rankings and writing deliverables ...")
    ranking_rows = aggregate_state_metrics(all_cell_records, state_names, min_cells=MIN_STATE_CELLS)
    ranking_csv_path = EXP_DIR / "ranking.csv"
    fieldnames = [
        "state",
        "state_name",
        "param",
        "season",
        "n_cells",
        "n_sig_fdr",
        "share_sig_fdr",
        "median_slope_sig",
        "median_slope_all",
        "n_sig_pos",
        "n_sig_neg",
        "dominant_sign",
        "consistency",
        "clarity_score",
    ]
    with ranking_csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(ranking_rows)
    print(f"   Wrote {ranking_csv_path.relative_to(ROOT)} ({len(ranking_rows)} rows).")

    # Write cells.csv.gz only if < 1 MB
    cells_gz_path = EXP_DIR / "cells.csv.gz"
    cell_fields = [
        "state",
        "lat",
        "lon",
        "param",
        "season",
        "slope_per_decade",
        "p",
        "q",
        "significant_raw",
        "significant_fdr",
    ]
    # Keep only cells in kept_states (>=4 cells)
    kept_cell_records = [r for r in all_cell_records if r["state"] in kept_states]
    with gzip.open(cells_gz_path, "wt", newline="", encoding="utf-8", compresslevel=9) as gz:
        writer = csv.DictWriter(gz, fieldnames=cell_fields)
        writer.writeheader()
        writer.writerows(kept_cell_records)
    gz_size = cells_gz_path.stat().st_size
    if gz_size >= 1_000_000:
        cells_gz_path.unlink()
        print(f"   Skipped cells.csv.gz ({gz_size} bytes >= 1 MB).")
    else:
        print(f"   Wrote {cells_gz_path.relative_to(ROOT)} ({gz_size / 1024:.1f} KB < 1 MB).")

    # Save summary JSON in scratch for inspection
    temp_ranking = rank_temperature_states(ranking_rows)
    summary_data = {
        "runtime_seconds": round(time.perf_counter() - t_start, 2),
        "failed_tiles": all_failed_tiles,
        "dropped_states": dropped_states,
        "kept_state_count": len(kept_states),
        "fdr_summary": fdr_summary,
        "temperature_ranking": temp_ranking,
    }
    (SCRATCH_DIR / "summary.json").write_text(json.dumps(summary_data, indent=2), encoding="utf-8")
    print(f"Done in {time.perf_counter() - t_start:.2f}s.")


if __name__ == "__main__":
    main()
