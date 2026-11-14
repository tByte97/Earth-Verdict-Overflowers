#!/usr/bin/env python3
"""Fetch NASA NEX-GDDP-CMIP6 daily point series via NCCS THREDDS NCSS and aggregate seasonally.

Standard library only. Caches catalog XMLs and NCSS CSV responses in data/cache/.

Examples:
  python3 tools/fetch_cmip6.py kyiv --models ACCESS-CM2
  python3 tools/fetch_cmip6.py kyiv
  python3 tools/fetch_cmip6.py --all
  python3 tools/fetch_cmip6.py --lat 50.45 --lon 30.52 --name kyiv --models ACCESS-CM2 GFDL-ESM4
"""
import argparse
import concurrent.futures
import csv
import hashlib
import io
import json
import math
import os
import random
import re
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = DATA / "cache"
OUT_DIR = DATA / "cmip6"
UA = {"User-Agent": "Mozilla/5.0 (EarthVerdict hackathon fetcher)"}

CATALOG_BASE = "https://ds.nccs.nasa.gov/thredds/catalog/AMES/NEX/GDDP-CMIP6"
NCSS_BASE = "https://ds.nccs.nasa.gov/thredds/ncss/grid"
THREDDS_NS = {"c": "http://www.unidata.ucar.edu/namespaces/thredds/InvCatalog/v1.0"}

CITIES = {
    "kyiv": ("Київ", 50.45, 30.52),
    "lviv": ("Львів", 49.84, 24.03),
    "odesa": ("Одеса", 46.48, 30.73),
    "kharkiv": ("Харків", 49.99, 36.23),
    "warsaw": ("Варшава", 52.23, 21.01),
}

DEFAULT_MODELS = [
    "ACCESS-CM2",
    "GFDL-ESM4",
    "IPSL-CM6A-LR",
    "MIROC6",
    "MPI-ESM1-2-HR",
]

SCENARIOS = ["ssp126", "ssp245", "ssp585"]
VARIABLES = ["tas", "pr"]
SEASONS = ["JJA", "DJF", "year"]
HIST_START, HIST_END = 1995, 2014
# Fetch 1994 in historical so DJF 1995 has December 1994.
HIST_FETCH_START = HIST_START - 1
SSP_START, SSP_END = 2015, 2100
HORIZON_YEARS = [2030, 2050, 2070, 2100]

YEAR_RE = re.compile(r"_(\d{4})(?:_v[\d.]+)?\.nc$")
_CACHE_LOCK = threading.Lock()


def normalize_lon(lon):
    """Normalize longitude into [-180, 180] for THREDDS NCSS."""
    return ((lon + 180.0) % 360.0) - 180.0


def _atomic_write(path, text):
    CACHE.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp_", dir=str(CACHE))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def get_text(url, params=None, refresh=False, retries=5, ext="txt", validate=None):
    """GET with file cache in data/cache/ and exponential-backoff retries."""
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    path = CACHE / f"{hashlib.sha1(full.encode()).hexdigest()[:16]}.{ext}"
    if path.exists() and not refresh:
        return path.read_text(encoding="utf-8")

    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(full, headers=UA)
            with urllib.request.urlopen(req, timeout=180) as r:
                text = r.read().decode("utf-8")
            if validate:
                validate(text)
            with _CACHE_LOCK:
                _atomic_write(path, text)
            return text
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500 and e.code != 429:
                raise RuntimeError(f"HTTP {e.code} for {full}: {e.read()[:200]!r}")
            last = e
        except Exception as e:
            last = e
        delay = min(30.0, 2.0 * (2 ** attempt)) + random.uniform(0.1, 0.8)
        time.sleep(delay)
    raise RuntimeError(f"Failed to fetch {full}: {last}")


def _validate_xml(text):
    ET.fromstring(text)


def _validate_ncss_csv(var):
    def _check(text):
        lines = text.strip().splitlines()
        if len(lines) < 350:
            raise ValueError(f"Unexpectedly short NCSS CSV ({len(lines)} lines)")
        if f"{var}[" not in lines[0] and f",{var}" not in lines[0]:
            raise ValueError(f"Missing variable {var!r} in CSV header: {lines[0][:120]}")
    return _check


def get_xml(url, refresh=False):
    return ET.fromstring(get_text(url, refresh=refresh, ext="xml", validate=_validate_xml))


def catalog_children(url, refresh=False):
    root = get_xml(url, refresh=refresh)
    return [el.attrib["name"] for el in root.findall(".//c:catalogRef", THREDDS_NS) if "name" in el.attrib]


def pick_variant(model, refresh=False):
    """Pick a common ensemble variant across historical and all SSPs (prefer r1i1p1f1)."""
    needed = ["historical", *SCENARIOS]
    avail_scens = set(catalog_children(f"{CATALOG_BASE}/{model}/catalog.xml", refresh=refresh))
    missing = [s for s in needed if s not in avail_scens]
    if missing:
        raise RuntimeError(f"Model {model} is missing scenarios: {missing}")

    per_scen = [
        set(catalog_children(f"{CATALOG_BASE}/{model}/{s}/catalog.xml", refresh=refresh))
        for s in needed
    ]
    common = set.intersection(*per_scen)
    if not common:
        raise RuntimeError(f"Model {model} has no common variant across {needed}")
    return "r1i1p1f1" if "r1i1p1f1" in common else sorted(common)[0]


def list_year_paths(model, scenario, variant, var, refresh=False):
    """Return {year: urlPath} from the THREDDS catalog for model/scenario/variant/var."""
    url = f"{CATALOG_BASE}/{model}/{scenario}/{variant}/{var}/catalog.xml"
    root = get_xml(url, refresh=refresh)
    paths = {}
    for el in root.findall(".//c:dataset", THREDDS_NS):
        up = el.attrib.get("urlPath")
        if not up:
            continue
        m = YEAR_RE.search(up)
        if m:
            paths[int(m.group(1))] = up
    return paths


def fetch_year_csv(url_path, var, lat, lon, refresh=False):
    """Fetch one year's daily CSV via NCSS and return (grid_lat, grid_lon, rows)."""
    url = f"{NCSS_BASE}/{url_path}"
    params = {
        "var": var,
        "latitude": f"{lat:.4f}",
        "longitude": f"{normalize_lon(lon):.4f}",
        "temporal": "all",
        "accept": "csv",
    }
    text = get_text(url, params=params, refresh=refresh, ext="csv", validate=_validate_ncss_csv(var))
    reader = csv.reader(io.StringIO(text))
    header = next(reader)
    lat_col = next(i for i, h in enumerate(header) if h.startswith("latitude"))
    lon_col = next(i for i, h in enumerate(header) if h.startswith("longitude"))
    val_col = next(i for i, h in enumerate(header) if h == var or h.startswith(f"{var}["))

    grid_lat = None
    grid_lon = None
    daily = []
    for row in reader:
        if not row:
            continue
        date_str = row[0][:10]
        y, m, d = map(int, date_str.split("-"))
        raw = row[val_col].strip()
        if not raw or raw.lower() in ("nan", "na"):
            continue
        val = float(raw)
        if not math.isfinite(val) or abs(val) > 1e15:
            continue
        if grid_lat is None:
            grid_lat = float(row[lat_col])
            grid_lon = float(row[lon_col])
        daily.append((y, m, d, val))
    return grid_lat, grid_lon, daily


def aggregate_seasonal(daily_records, var, years):
    """Aggregate daily (year, month, day, raw_val) into seasonal {season: {year: val}}.

    tas: Kelvin -> °C mean over days in season.
    pr: kg m-2 s-1 -> mm/day (*86400) sum over days in season.
    DJF for year Y uses Dec (Y-1), Jan (Y), Feb (Y).
    """
    buckets = {s: {} for s in SEASONS}
    for y, m, _d, raw in daily_records:
        val = (raw - 273.15) if var == "tas" else (raw * 86400.0)
        buckets["year"].setdefault((y, 0), []).append(val)
        if m in (6, 7, 8):
            buckets["JJA"].setdefault((y, 0), []).append(val)
        if m == 12:
            buckets["DJF"].setdefault((y + 1, 12), []).append(val)
        elif m in (1, 2):
            buckets["DJF"].setdefault((y, m), []).append(val)

    out = {s: {} for s in SEASONS}
    for y in years:
        y_vals = buckets["year"].get((y, 0))
        out["year"][y] = round(sum(y_vals) / len(y_vals) if var == "tas" else sum(y_vals), 3) if y_vals else None

        jja_vals = buckets["JJA"].get((y, 0))
        out["JJA"][y] = round(sum(jja_vals) / len(jja_vals) if var == "tas" else sum(jja_vals), 3) if jja_vals else None

        dec_vals = buckets["DJF"].get((y, 12))
        jan_vals = buckets["DJF"].get((y, 1))
        feb_vals = buckets["DJF"].get((y, 2))
        if dec_vals and jan_vals and feb_vals:
            djf_all = dec_vals + jan_vals + feb_vals
            out["DJF"][y] = round(sum(djf_all) / len(djf_all) if var == "tas" else sum(djf_all), 3)
        else:
            out["DJF"][y] = None
    return out


def percentile(values, q):
    """Linear-interpolation percentile matching numpy default (q in 0..100)."""
    xs = sorted(values)
    if not xs:
        return None
    if len(xs) == 1:
        return xs[0]
    pos = (q / 100.0) * (len(xs) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return xs[lo]
    frac = pos - lo
    return xs[lo] + frac * (xs[hi] - xs[lo])


def centered_window(target_year, y_min=SSP_START, y_max=SSP_END):
    """20-year centered window [T-9, T+10] clamped to [y_min, y_max]."""
    return max(y_min, target_year - 9), min(y_max, target_year + 10)


def build_city(key, name, lat, lon, models, workers, refresh):
    t_city = time.time()
    print(f"{name} ({lat}, {lon}) — models: {', '.join(models)}")

    # 1. Discover catalog paths for all models/scenarios/vars
    variants = {}
    tasks = []
    for model in models:
        variant = pick_variant(model, refresh=refresh)
        variants[model] = variant
        for scen in ["historical", *SCENARIOS]:
            y0, y1 = (HIST_FETCH_START, HIST_END) if scen == "historical" else (SSP_START, SSP_END)
            for var in VARIABLES:
                ymap = list_year_paths(model, scen, variant, var, refresh=refresh)
                missing = [y for y in range(y0, y1 + 1) if y not in ymap]
                if missing:
                    raise RuntimeError(f"{model}/{scen}/{variant}/{var} missing years: {missing[:5]}")
                for y in range(y0, y1 + 1):
                    tasks.append((model, scen, var, y, ymap[y]))

    total = len(tasks)
    print(f"  {total} file-year point queries queued (workers={workers})")

    # 2. Fetch concurrently with cache + progress reporting
    raw_daily = {}  # (model, scen, var) -> list of (y, m, d, val)
    grid_cells = {}
    done = 0
    t_fetch = time.time()

    def _run_one(task):
        model, scen, var, y, url_path = task
        glat, glon, rows = fetch_year_csv(url_path, var, lat, lon, refresh=refresh)
        return model, scen, var, glat, glon, rows

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(_run_one, t) for t in tasks]
        for fut in concurrent.futures.as_completed(futures):
            model, scen, var, glat, glon, rows = fut.result()
            raw_daily.setdefault((model, scen, var), []).extend(rows)
            if glat is not None and model not in grid_cells:
                grid_cells[model] = [glat, glon]
            done += 1
            if done % 100 == 0 or done == total:
                elapsed = time.time() - t_fetch
                rate = done / elapsed if elapsed > 0 else 0
                eta = (total - done) / rate if rate > 0 else 0
                print(f"  progress: {done}/{total} ({elapsed:.1f}s elapsed, ~{eta:.0f}s ETA)", flush=True)

    # 3. Aggregate seasonal values per model
    hist_years = list(range(HIST_START, HIST_END + 1))
    ssp_years = list(range(SSP_START, SSP_END + 1))
    model_seasonal = {}  # (model, scen, var) -> {season: {year: val}}
    dec_2014 = {}  # (model, var) -> list of Dec 2014 records for DJF 2015

    for model in models:
        for var in VARIABLES:
            h_rows = raw_daily[(model, "historical", var)]
            model_seasonal[(model, "historical", var)] = aggregate_seasonal(h_rows, var, hist_years)
            dec_2014[(model, var)] = [r for r in h_rows if r[0] == HIST_END and r[1] == 12]
            for scen in SCENARIOS:
                s_rows = dec_2014[(model, var)] + raw_daily[(model, scen, var)]
                model_seasonal[(model, scen, var)] = aggregate_seasonal(s_rows, var, ssp_years)

    # 4. Compute baselines, annual changes, and 20-yr centered horizons
    windows_meta = {str(y): f"{a}-{b}" for y in HORIZON_YEARS for a, b in [centered_window(y)]}
    annual_vars = {}
    horizon_vars = {}

    for var in VARIABLES:
        digits = 2 if var == "tas" else 1
        annual_vars[var] = {}
        horizon_vars[var] = {}
        for season in SEASONS:
            hist_by_model = {}
            baseline_by_model = {}
            for model in models:
                h_series = [model_seasonal[(model, "historical", var)][season][y] for y in hist_years]
                hist_by_model[model] = h_series
                valid = [v for v in h_series if v is not None]
                baseline_by_model[model] = round(sum(valid) / len(valid), 3)

            ann_season = {
                "historical_by_model": hist_by_model,
                "baseline_by_model": baseline_by_model,
            }
            hor_season = {}

            for scen in SCENARIOS:
                raw_by_model = {}
                delta_by_model = {}
                for model in models:
                    base = baseline_by_model[model]
                    s_map = model_seasonal[(model, scen, var)][season]
                    raw_by_model[model] = [s_map[y] for y in ssp_years]
                    delta_by_model[model] = [
                        round(s_map[y] - base, 3) if s_map[y] is not None else None
                        for y in ssp_years
                    ]

                med, p10, p90 = [], [], []
                for idx in range(len(ssp_years)):
                    vals = [delta_by_model[m][idx] for m in models if delta_by_model[m][idx] is not None]
                    med.append(round(percentile(vals, 50), digits))
                    p10.append(round(percentile(vals, 10), digits))
                    p90.append(round(percentile(vals, 90), digits))

                ann_season[scen] = {
                    "median": med,
                    "low": p10,
                    "high": p90,
                    "change_by_model": delta_by_model,
                    "raw_by_model": raw_by_model,
                }

                # 20-year centered means at horizon years
                h_med, h_p10, h_p90 = [], [], []
                h_by_model = {m: [] for m in models}
                for ty in HORIZON_YEARS:
                    w_start, w_end = centered_window(ty)
                    per_model_means = []
                    for model in models:
                        w_vals = [
                            delta_by_model[model][y - SSP_START]
                            for y in range(w_start, w_end + 1)
                            if delta_by_model[model][y - SSP_START] is not None
                        ]
                        m_mean = sum(w_vals) / len(w_vals)
                        h_by_model[model].append(round(m_mean, digits))
                        per_model_means.append(m_mean)
                    h_med.append(round(percentile(per_model_means, 50), digits))
                    h_p10.append(round(percentile(per_model_means, 10), digits))
                    h_p90.append(round(percentile(per_model_means, 90), digits))

                hor_season[scen] = {
                    "median": h_med,
                    "low": h_p10,
                    "high": h_p90,
                    "by_model": h_by_model,
                }

            annual_vars[var][season] = ann_season
            horizon_vars[var][season] = hor_season

    any_cell = next(iter(grid_cells.values()), [lat, lon])
    out = {
        "name": name,
        "city_key": key,
        "lat": lat,
        "lon": lon,
        "grid_cell": any_cell,
        "retrieved": time.strftime("%Y-%m-%d"),
        "source": "NASA NEX-GDDP-CMIP6 via NCCS THREDDS NCSS",
        "catalog_url": f"{CATALOG_BASE}/catalog.html",
        "models": models,
        "variants": variants,
        "baseline_period": f"{HIST_START}-{HIST_END}",
        "units": {"tas": "°C", "pr": "mm"},
        "horizons": {
            "years": HORIZON_YEARS,
            "windows": windows_meta,
            "variables": horizon_vars,
        },
        "annual": {
            "historical_years": hist_years,
            "ssp_years": ssp_years,
            "variables": annual_vars,
        },
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"{key}.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    elapsed_total = time.time() - t_city
    print(f"  saved {out_path.relative_to(ROOT)} ({out_path.stat().st_size // 1024} KB) in {elapsed_total:.1f}s")
    return out


def parse_models(raw_models):
    if not raw_models:
        return list(DEFAULT_MODELS)
    out = []
    for item in raw_models:
        for part in item.split(","):
            part = part.strip()
            if part and part not in out:
                out.append(part)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cities", nargs="*", help=f"city keys: {', '.join(CITIES)}")
    ap.add_argument("--all", action="store_true", help="fetch all cities in CITIES")
    ap.add_argument("--lat", type=float, help="custom latitude")
    ap.add_argument("--lon", type=float, help="custom longitude")
    ap.add_argument("--name", default="custom", help="output key/name for custom coordinates")
    ap.add_argument("--models", nargs="+", help=f"CMIP6 models (default: {', '.join(DEFAULT_MODELS)})")
    ap.add_argument("--workers", type=int, default=6, help="concurrent NCSS requests (max 6)")
    ap.add_argument("--refresh", action="store_true", help="ignore data/cache/")
    a = ap.parse_args()

    workers = max(1, min(a.workers, 6))
    models = parse_models(a.models)

    jobs = []
    if a.lat is not None and a.lon is not None:
        jobs.append((a.name, a.name, a.lat, a.lon))
    keys = list(CITIES) if a.all else a.cities
    for k in keys:
        if k not in CITIES:
            sys.exit(f"Unknown city '{k}'. Available: {', '.join(CITIES)}")
        n, la, lo = CITIES[k]
        jobs.append((k, n, la, lo))
    if not jobs:
        ap.error("specify city, --all, or --lat/--lon")

    for key, name, lat, lon in jobs:
        build_city(key, name, lat, lon, models, workers, a.refresh)


if __name__ == "__main__":
    main()
