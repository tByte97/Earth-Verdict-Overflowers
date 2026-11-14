#!/usr/bin/env python3
"""Fetch NASA NEX-GDDP-CMIP6 daily bounding-box slices via NCCS THREDDS NCSS and aggregate regionally.

Dependencies: Python 3.10+ stdlib, numpy, scipy.

Pipeline:
  1. Discover model variants and yearly dataset paths from NCCS THREDDS catalog.xml.
  2. Download each (model, scenario, var, year) bbox as NetCDF-3 via NCSS, immediately
     reduce daily grids to monthly values float32 (12, nlat, nlon), and delete the .nc file:
       - tas: monthly mean in degC (K - 273.15)
       - pr:  monthly sum in mm (mean(kg m-2 s-1) * 86400 * days_in_month_in_calendar)
     Reduced arrays are written atomically to data/cache/cmip6-region/<name>/.
  3. Finalize into data/cmip6/region-<name>.json (compact JSON, no whitespace):
       - Compute seasonal values (JJA, DJF using Dec of year Y-1 + Jan/Feb of Y, year).
       - Per-model 1995-2014 historical baseline and seasonal changes relative to baseline.
       - 20-year centered window means at horizons [2030, 2050, 2070, 2100].
       - Multi-model ensemble 50th (median), 10th (low), and 90th (high) percentiles per cell.

Output JSON array layout (`data/cmip6/region-<name>.json`):
  - `grid.lat`: list of `nlat` latitudes (ascending, degrees_north)
  - `grid.lon`: list of `nlon` longitudes (converted from 0..360 to -180..180, degrees_east)
  - `baseline[var][season]`: 2D nested list `[lat_idx][lon_idx]` of ensemble-median 1995-2014
    baselines (tas in degC rounded to 2 decimals; pr in mm rounded to 1 decimal).
  - `variables[var][season][scenario][stat]`: 3D nested list `[horizon_idx][lat_idx][lon_idx]`
    where `horizon_idx` indexes `horizons.years` ([2030, 2050, 2070, 2100]), `stat` is
    `"median"`, `"low"`, or `"high"`, and values are changes relative to 1995-2014 baseline
    (degC for tas, mm for pr). Missing/ocean cells are JSON `null`.

Examples:
  python3 tools/fetch_cmip6_region.py --name europe-east --bbox 44 20 53 41 --estimate
  python3 tools/fetch_cmip6_region.py --name europe-east --bbox 44 20 53 41 --workers 4
  python3 tools/fetch_cmip6_region.py --name europe-east --bbox 44 20 53 41 --finalize-only
  python3 tools/fetch_cmip6_region.py --smoke
"""
from __future__ import annotations

import argparse
import calendar
import concurrent.futures
import datetime
import json
import math
import os
import random
import re
import signal
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
from scipy.io import netcdf_file

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import fetch_cmip6 as pt  # noqa: E402

ROOT = pt.ROOT
DATA = pt.DATA
OUT_DIR = pt.OUT_DIR
REGION_CACHE_ROOT = DATA / "cache" / "cmip6-region"

DEFAULT_MODELS = list(pt.DEFAULT_MODELS)
SCENARIOS = list(pt.SCENARIOS)
VARIABLES = list(pt.VARIABLES)
SEASONS = list(pt.SEASONS)
HIST_START = pt.HIST_START
HIST_END = pt.HIST_END
HIST_FETCH_START = pt.HIST_FETCH_START
SSP_START = pt.SSP_START
SSP_END = pt.SSP_END
HORIZON_YEARS = list(pt.HORIZON_YEARS)
CATALOG_BASE = pt.CATALOG_BASE
NCSS_BASE = pt.NCSS_BASE
UA = pt.UA

REQUEST_TIMEOUT_S = 300
ESTIMATE_SEC_PER_TASK = 27.0
MIN_COMPLETE_MODELS = 3

SMOKE_BBOX = [50.0, 30.0, 51.0, 31.0]
SMOKE_MODELS = ["ACCESS-CM2"]
SMOKE_HIST_YEARS = (2012, 2014)
SMOKE_SSP_SCENARIO = "ssp585"
SMOKE_SSP_YEARS = (2049, 2051)

_DAYS_NOLEAP = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
_CUM_DAYS_NOLEAP = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334, 365)
_TIME_UNITS_RE = re.compile(
    r"^\s*(days|hours|seconds)\s+since\s+(\d{4})-(\d{1,2})-(\d{1,2})"
    r"(?:[ T](\d{1,2}):(\d{1,2})(?::(\d{1,2}(?:\.\d+)?))?)?",
    re.IGNORECASE,
)


class IncompatibleModelError(RuntimeError):
    """Raised when a model uses an unsupported calendar or incompatible grid."""


class MissingDataError(RuntimeError):
    """Raised when an HTTP 404 or empty/invalid file prevents completing a task."""


def to_lon360(lon: float) -> float:
    """Convert longitude to [0, 360) for NEX-GDDP-CMIP6 0-360 grid queries."""
    return lon % 360.0


def to_lon180(lon: float) -> float:
    """Normalize longitude into (-180, 180] for output JSON."""
    x = ((lon + 180.0) % 360.0) - 180.0
    if x == -180.0 and lon > 0:
        return 180.0
    return x


def validate_bbox(bbox: list[float]) -> tuple[float, float, float, float]:
    """Validate and return (south, west, north, east)."""
    if len(bbox) != 4:
        raise ValueError("bbox must have 4 values: SOUTH WEST NORTH EAST")
    south, west, north, east = map(float, bbox)
    if not (-90.0 <= south < north <= 90.0):
        raise ValueError(f"Invalid latitude bounds: south={south}, north={north}")
    if not (-180.0 <= west <= 360.0 and -180.0 <= east <= 360.0):
        raise ValueError(f"Invalid longitude bounds: west={west}, east={east}")
    if west == east:
        raise ValueError("west and east longitudes must differ")
    return south, west, north, east


def _decode_attr(val, default: str = "") -> str:
    if val is None:
        return default
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    return str(val)


def _noleap_days_in_month(month: int) -> int:
    return _DAYS_NOLEAP[month - 1]


def _noleap_ymd_from_offset(ref_y: int, ref_m: int, ref_d: int, day_offset: int) -> tuple[int, int]:
    total = ref_y * 365 + _CUM_DAYS_NOLEAP[ref_m - 1] + (ref_d - 1) + day_offset
    y, doy = divmod(total, 365)
    for m in range(1, 13):
        if doy < _CUM_DAYS_NOLEAP[m]:
            return y, m
    raise RuntimeError(f"Invalid day of year {doy}")


def decode_time_axis(time_vals: np.ndarray, units: str, cal: str) -> tuple[list[tuple[int, int]], dict[tuple[int, int], int]]:
    """Map NetCDF time coordinate values to (year, month) and calendar month lengths.

    Supports `365_day`/`noleap` and `proleptic_gregorian`/`standard`/`gregorian`.
    Raises IncompatibleModelError for `360_day` or unknown calendars.
    """
    m = _TIME_UNITS_RE.match(units or "")
    if not m:
        raise ValueError(f"Unsupported time units: {units!r}")
    unit_name = m.group(1).lower()
    ref_y, ref_m, ref_d = int(m.group(2)), int(m.group(3)), int(m.group(4))
    hh = int(m.group(5) or 0)
    mm = int(m.group(6) or 0)
    ss = float(m.group(7) or 0.0)

    scale_to_days = {"days": 1.0, "hours": 1.0 / 24.0, "seconds": 1.0 / 86400.0}[unit_name]
    cal_norm = (cal or "standard").strip().lower()

    if cal_norm in ("360_day",):
        raise IncompatibleModelError(f"Unsupported 360_day calendar ({cal!r})")

    ym_list: list[tuple[int, int]] = []
    days_per_ym: dict[tuple[int, int], int] = {}

    if cal_norm in ("365_day", "noleap"):
        ref_frac = (hh * 3600.0 + mm * 60.0 + ss) / 86400.0
        for raw_t in time_vals:
            day_offset = int(math.floor(float(raw_t) * scale_to_days + ref_frac + 1e-6))
            ym = _noleap_ymd_from_offset(ref_y, ref_m, ref_d, day_offset)
            ym_list.append(ym)
            if ym not in days_per_ym:
                days_per_ym[ym] = _noleap_days_in_month(ym[1])
        return ym_list, days_per_ym

    if cal_norm in ("proleptic_gregorian", "standard", "gregorian"):
        ref_dt = datetime.datetime(ref_y, ref_m, ref_d, hh, mm, int(ss))
        for raw_t in time_vals:
            dt = ref_dt + datetime.timedelta(days=float(raw_t) * scale_to_days)
            ym = (dt.year, dt.month)
            ym_list.append(ym)
            if ym not in days_per_ym:
                days_per_ym[ym] = calendar.monthrange(ym[0], ym[1])[1]
        return ym_list, days_per_ym

    raise IncompatibleModelError(f"Unsupported calendar: {cal!r}")


def reduce_nc_to_monthly(
    nc_path: Path, var: str, expected_year: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Read NetCDF-3 bbox file and reduce daily variable to float32 (12, nlat, nlon).

    Returns (monthly_array, lat_1d, lon_1d_neg180_to_180).
    """
    with netcdf_file(str(nc_path), "r", mmap=False) as nc:
        for req_name in ("time", "lat", "lon", var):
            if req_name not in nc.variables:
                raise MissingDataError(f"Variable {req_name!r} missing from {nc_path.name}")

        lat = np.asarray(nc.variables["lat"].data, dtype=np.float64).copy()
        lon_raw = np.asarray(nc.variables["lon"].data, dtype=np.float64).copy()
        lon = np.array([to_lon180(float(x)) for x in lon_raw], dtype=np.float64)

        t_var = nc.variables["time"]
        t_vals = np.asarray(t_var.data, dtype=np.float64)
        units = _decode_attr(t_var._attributes.get("units"))
        cal = _decode_attr(t_var._attributes.get("calendar"), "standard")
        ym_list, days_per_ym = decode_time_axis(t_vals, units, cal)

        v = nc.variables[var]
        raw = np.asarray(v.data, dtype=np.float64).copy()
        if raw.ndim != 3:
            raise MissingDataError(f"Expected 3D array for {var}, got shape {raw.shape}")
        if raw.shape[0] != len(ym_list):
            raise MissingDataError(f"Time length mismatch: {raw.shape[0]} vs {len(ym_list)}")

        attrs = v._attributes
        mask = ~np.isfinite(raw) | (np.abs(raw) > 1e15)
        for fill_key in ("_FillValue", "missing_value"):
            if fill_key in attrs:
                fv = float(np.asarray(attrs[fill_key]).flat[0])
                if np.isfinite(fv):
                    mask |= raw == fv
        raw[mask] = np.nan

        if "scale_factor" in attrs:
            raw = raw * float(np.asarray(attrs["scale_factor"]).flat[0])
        if "add_offset" in attrs:
            raw = raw + float(np.asarray(attrs["add_offset"]).flat[0])

    nlat, nlon = lat.shape[0], lon.shape[0]
    monthly = np.full((12, nlat, nlon), np.nan, dtype=np.float32)

    ym_arr = np.asarray(ym_list, dtype=np.int32)
    for month in range(1, 13):
        idx = np.where((ym_arr[:, 0] == expected_year) & (ym_arr[:, 1] == month))[0]
        if idx.size == 0:
            continue
        sub = raw[idx]
        valid = np.isfinite(sub)
        cnt = valid.sum(axis=0)
        total = np.where(valid, sub, 0.0).sum(axis=0)
        with np.errstate(invalid="ignore", divide="ignore"):
            mean = np.where(cnt > 0, total / np.maximum(cnt, 1), np.nan)
        if var == "tas":
            monthly[month - 1] = (mean - 273.15).astype(np.float32)
        elif var == "pr":
            n_days = days_per_ym[(expected_year, month)]
            monthly[month - 1] = (mean * 86400.0 * n_days).astype(np.float32)
        else:
            raise ValueError(f"Unsupported variable {var!r}")

    return monthly, lat, lon


def atomic_write_npy(path: Path, arr: np.ndarray) -> None:
    """Atomically write a numpy array to `path`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp_", suffix=".npy", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            np.save(f, arr)
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def atomic_write_text(path: Path, text: str) -> None:
    """Atomically write UTF-8 text to `path`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp_", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def download_ncss_netcdf(
    url_path: str,
    var: str,
    bbox: tuple[float, float, float, float],
    dest_nc: Path,
    stop_event: threading.Event | None = None,
    retries: int = 5,
    timeout: int = REQUEST_TIMEOUT_S,
) -> None:
    """Download one year's NCSS bbox NetCDF-3 file with exponential backoff and jitter."""
    south, west, north, east = bbox
    params = {
        "var": var,
        "north": f"{north:.4f}",
        "south": f"{south:.4f}",
        "west": f"{to_lon360(west):.4f}",
        "east": f"{to_lon360(east):.4f}",
        "temporal": "all",
        "accept": "netcdf",
    }
    full_url = f"{NCSS_BASE}/{url_path}?{urllib.parse.urlencode(params)}"

    last_err: Exception | None = None
    for attempt in range(retries):
        if stop_event is not None and stop_event.is_set():
            raise InterruptedError("Download cancelled by stop signal")
        try:
            req = urllib.request.Request(full_url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
            if len(data) < 256 or not data.startswith(b"CDF"):
                raise MissingDataError(
                    f"Empty or non-NetCDF3 response ({len(data)} bytes) for {full_url}"
                )
            dest_nc.parent.mkdir(parents=True, exist_ok=True)
            dest_nc.write_bytes(data)
            return
        except urllib.error.HTTPError as e:
            if e.code == 404 or (400 <= e.code < 500 and e.code != 429):
                raise MissingDataError(f"HTTP {e.code} for {full_url}") from e
            last_err = e
        except MissingDataError:
            raise
        except Exception as e:
            last_err = e

        if attempt + 1 < retries:
            delay = min(60.0, 2.0 * (2 ** attempt)) + random.uniform(0.1, 1.0)
            if stop_event is not None:
                if stop_event.wait(delay):
                    raise InterruptedError("Download cancelled during backoff")
            else:
                time.sleep(delay)

    raise RuntimeError(f"Failed after {retries} attempts for {full_url}: {last_err}")


def npy_cache_path(cache_dir: Path, model: str, scen: str, var: str, year: int) -> Path:
    return cache_dir / f"{model}_{scen}_{var}_{year}.npy"


def _grid_cache_path(cache_dir: Path) -> Path:
    return cache_dir / "grid.json"


def verify_and_store_grid(
    cache_dir: Path, lat: np.ndarray, lon: np.ndarray, lock: threading.Lock, model: str
) -> None:
    """Ensure lat/lon grid matches across all models and persist grid.json."""
    grid_path = _grid_cache_path(cache_dir)
    with lock:
        if grid_path.exists():
            ref = json.loads(grid_path.read_text(encoding="utf-8"))
            ref_lat = np.asarray(ref["lat"], dtype=np.float64)
            ref_lon = np.asarray(ref["lon"], dtype=np.float64)
            if lat.shape != ref_lat.shape or lon.shape != ref_lon.shape:
                raise IncompatibleModelError(
                    f"Grid shape mismatch for {model}: {(lat.shape, lon.shape)} vs {(ref_lat.shape, ref_lon.shape)}"
                )
            if not (np.allclose(lat, ref_lat, atol=1e-4) and np.allclose(lon, ref_lon, atol=1e-4)):
                raise IncompatibleModelError(
                    f"Grid coordinates differ for {model}: lat/lon mismatch against reference grid"
                )
            assert np.allclose(lat, ref_lat, atol=1e-4)
            assert np.allclose(lon, ref_lon, atol=1e-4)
        else:
            payload = {
                "lat": [round(float(x), 4) for x in lat],
                "lon": [round(float(x), 4) for x in lon],
            }
            atomic_write_text(grid_path, json.dumps(payload, separators=(",", ":")))


def build_task_plan(
    models: list[str],
    smoke: bool = False,
    refresh: bool = False,
) -> tuple[list[tuple[str, str, str, int, str]], dict[str, str], dict[str, set[str]]]:
    """Discover THREDDS catalog paths and return (tasks, variants, failed_models)."""
    tasks: list[tuple[str, str, str, int, str]] = []
    variants: dict[str, str] = {}
    failed_models: dict[str, set[str]] = {}

    if smoke:
        scen_ranges = [("historical", SMOKE_HIST_YEARS[0], SMOKE_HIST_YEARS[1]),
                       (SMOKE_SSP_SCENARIO, SMOKE_SSP_YEARS[0], SMOKE_SSP_YEARS[1])]
    else:
        scen_ranges = [("historical", HIST_FETCH_START, HIST_END)] + [
            (s, SSP_START, SSP_END) for s in SCENARIOS
        ]

    for model in models:
        try:
            variant = pt.pick_variant(model, refresh=refresh)
        except Exception as e:
            print(f"[warn] skipping model {model}: variant discovery failed: {e}", flush=True)
            failed_models.setdefault(model, set()).add(f"variant discovery: {e}")
            continue
        variants[model] = variant
        model_tasks = []
        ok = True
        for scen, y0, y1 in scen_ranges:
            for var in VARIABLES:
                try:
                    ymap = pt.list_year_paths(model, scen, variant, var, refresh=refresh)
                except Exception as e:
                    print(f"[warn] {model}/{scen}/{var}: catalog failed: {e}", flush=True)
                    failed_models.setdefault(model, set()).add(f"catalog {scen}/{var}: {e}")
                    ok = False
                    break
                missing = [y for y in range(y0, y1 + 1) if y not in ymap]
                if missing:
                    msg = f"{model}/{scen}/{variant}/{var} missing years in catalog: {missing[:5]}"
                    print(f"[warn] {msg}", flush=True)
                    failed_models.setdefault(model, set()).add(msg)
                    ok = False
                    break
                for y in range(y0, y1 + 1):
                    model_tasks.append((model, scen, var, y, ymap[y]))
            if not ok:
                break
        if ok:
            tasks.extend(model_tasks)
    return tasks, variants, failed_models


def count_all_expected_tasks(models: list[str], smoke: bool = False) -> int:
    """Count total (model, scen, var, year) tasks without contacting THREDDS."""
    if smoke:
        n_years = (SMOKE_HIST_YEARS[1] - SMOKE_HIST_YEARS[0] + 1) + (
            SMOKE_SSP_YEARS[1] - SMOKE_SSP_YEARS[0] + 1
        )
    else:
        n_years = (HIST_END - HIST_FETCH_START + 1) + len(SCENARIOS) * (SSP_END - SSP_START + 1)
    return len(models) * len(VARIABLES) * n_years


def _format_duration(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}h {m}m"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


def run_downloads(
    name: str,
    bbox: tuple[float, float, float, float],
    models: list[str],
    workers: int,
    cache_dir: Path,
    smoke: bool = False,
    refresh: bool = False,
    max_hours: float | None = None,
) -> tuple[bool, set[str]]:
    """Run catalog discovery and parallel NCSS downloads -> monthly .npy cache.

    Returns (finished_all_queued, incomplete_models).
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    pt.CACHE = cache_dir / "_catalog"

    tasks, _variants, failed_discovery = build_task_plan(models, smoke=smoke, refresh=refresh)
    incomplete_models = set(failed_discovery.keys())

    pending = [
        t for t in tasks
        if refresh or not npy_cache_path(cache_dir, t[0], t[1], t[2], t[3]).exists()
    ]
    skipped = len(tasks) - len(pending)
    print(
        f"Region {name!r} bbox={list(bbox)}: {len(tasks)} total tasks, "
        f"{skipped} cached, {len(pending)} to fetch (workers={workers})",
        flush=True,
    )
    if not pending:
        return True, incomplete_models

    stop_event = threading.Event()
    grid_lock = threading.Lock()
    state_lock = threading.Lock()
    start_time = time.monotonic()
    deadline = start_time + max_hours * 3600.0 if max_hours is not None else None

    prev_sigint = signal.getsignal(signal.SIGINT)
    prev_sigterm = signal.getsignal(signal.SIGTERM)

    def _on_signal(signum, _frame):
        print(f"\n[signal] received signal {signum}; finishing active writes and stopping cleanly...", flush=True)
        stop_event.set()

    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, _on_signal)
        signal.signal(signal.SIGTERM, _on_signal)

    def _run_one(task: tuple[str, str, str, int, str]) -> tuple[str, str, str, int]:
        model, scen, var, year, url_path = task
        if stop_event.is_set():
            raise InterruptedError("Stopped")
        if deadline is not None and time.monotonic() >= deadline:
            stop_event.set()
            raise InterruptedError("Reached --max-hours")

        out_npy = npy_cache_path(cache_dir, model, scen, var, year)
        if not refresh and out_npy.exists():
            return model, scen, var, year

        fd, tmp_nc_name = tempfile.mkstemp(prefix=f".nc_{model}_{year}_", suffix=".nc", dir=str(cache_dir))
        os.close(fd)
        tmp_nc = Path(tmp_nc_name)
        try:
            download_ncss_netcdf(url_path, var, bbox, tmp_nc, stop_event=stop_event)
            monthly, lat, lon = reduce_nc_to_monthly(tmp_nc, var, year)
            verify_and_store_grid(cache_dir, lat, lon, grid_lock, model)
            atomic_write_npy(out_npy, monthly)
        finally:
            if tmp_nc.exists():
                tmp_nc.unlink()
        return model, scen, var, year

    done = 0
    errors = 0
    total = len(pending)
    cancelled = False

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            future_map = {}
            task_iter = iter(pending)

            def _submit_next() -> bool:
                if stop_event.is_set():
                    return False
                if deadline is not None and time.monotonic() >= deadline:
                    print("\n[max-hours] time budget reached; stopping cleanly...", flush=True)
                    stop_event.set()
                    return False
                try:
                    t = next(task_iter)
                except StopIteration:
                    return False
                fut = ex.submit(_run_one, t)
                future_map[fut] = t
                return True

            for _ in range(workers * 2):
                if not _submit_next():
                    break

            while future_map:
                finished, _ = concurrent.futures.wait(
                    future_map.keys(), timeout=1.0, return_when=concurrent.futures.FIRST_COMPLETED
                )
                if deadline is not None and time.monotonic() >= deadline and not stop_event.is_set():
                    print("\n[max-hours] time budget reached; finishing active writes...", flush=True)
                    stop_event.set()

                for fut in finished:
                    model, scen, var, year, _ = future_map.pop(fut)
                    try:
                        fut.result()
                        done += 1
                    except InterruptedError:
                        cancelled = True
                    except (MissingDataError, IncompatibleModelError, Exception) as exc:
                        errors += 1
                        done += 1
                        with state_lock:
                            incomplete_models.add(model)
                        print(f"[error] {model}/{scen}/{var}/{year}: {exc}", flush=True)

                    if done > 0 and (done % 25 == 0 or (not future_map and stop_event.is_set()) or done == total):
                        elapsed = time.monotonic() - start_time
                        rate = done / elapsed if elapsed > 0 else 0.0
                        eta = (total - done) / rate if rate > 0 else 0.0
                        print(
                            f"  progress: {done}/{total} ({rate:.2f} tasks/s, ~{_format_duration(eta)} ETA, errors={errors})",
                            flush=True,
                        )

                    if not stop_event.is_set():
                        _submit_next()
    finally:
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, prev_sigint)
            signal.signal(signal.SIGTERM, prev_sigterm)

    finished_all = (not stop_event.is_set()) and (not cancelled)
    return finished_all, incomplete_models


def _compute_seasonal(
    monthly_by_year: dict[int, np.ndarray],
    var: str,
    years: list[int],
    prev_dec_by_year: dict[int, np.ndarray] | None = None,
) -> dict[str, dict[int, np.ndarray]]:
    """Aggregate monthly (12, nlat, nlon) arrays into seasonal {season: {year: 2D array}}."""
    out: dict[str, dict[int, np.ndarray]] = {s: {} for s in SEASONS}
    for y in years:
        arr = monthly_by_year.get(y)
        if arr is None:
            continue
        if var == "tas":
            out["year"][y] = np.mean(arr, axis=0)
            out["JJA"][y] = np.mean(arr[[5, 6, 7]], axis=0)
        else:
            out["year"][y] = np.sum(arr, axis=0)
            out["JJA"][y] = np.sum(arr[[5, 6, 7]], axis=0)

        prev_arr = monthly_by_year.get(y - 1)
        dec = prev_arr[11] if prev_arr is not None else (prev_dec_by_year or {}).get(y - 1)
        if dec is not None:
            djf_stack = np.stack([dec, arr[0], arr[1]], axis=0)
            out["DJF"][y] = np.mean(djf_stack, axis=0) if var == "tas" else np.sum(djf_stack, axis=0)
    return out


def _nan_percentile_stack(stack: np.ndarray, q: float) -> np.ndarray:
    """Compute percentile q along axis=0 ignoring NaNs without empty-slice warnings."""
    valid_any = np.any(np.isfinite(stack), axis=0)
    out = np.full(stack.shape[1:], np.nan, dtype=np.float64)
    if np.any(valid_any):
        sub = stack[:, valid_any]
        out[valid_any] = np.nanpercentile(sub, q, axis=0)
    return out


def _to_json_grid(arr: np.ndarray, digits: int) -> list:
    """Convert 2D array to nested lists with rounded floats and None for non-finite cells."""
    rounded = np.round(arr.astype(np.float64), digits)
    finite = np.isfinite(rounded)
    out = []
    for i in range(rounded.shape[0]):
        row_vals = rounded[i]
        row_ok = finite[i]
        out.append([float(row_vals[j]) if row_ok[j] else None for j in range(rounded.shape[1])])
    return out


def _find_complete_models(
    cache_dir: Path,
    models: list[str],
    scenarios: list[str],
    hist_years: list[int],
    ssp_years: list[int],
) -> tuple[list[str], dict[str, int]]:
    """Return (complete_models, missing_count_by_model)."""
    complete = []
    missing_counts = {}
    for model in models:
        missing = 0
        for var in VARIABLES:
            for y in hist_years:
                if not npy_cache_path(cache_dir, model, "historical", var, y).exists():
                    missing += 1
            for scen in scenarios:
                for y in ssp_years:
                    if not npy_cache_path(cache_dir, model, scen, var, y).exists():
                        missing += 1
        if missing == 0:
            complete.append(model)
        else:
            missing_counts[model] = missing
    return complete, missing_counts


def finalize_region(
    name: str,
    bbox: tuple[float, float, float, float],
    models: list[str],
    cache_dir: Path,
    out_dir: Path = OUT_DIR,
    smoke: bool = False,
) -> tuple[dict, Path]:
    """Assemble regional JSON from cached monthly .npy files."""
    grid_path = _grid_cache_path(cache_dir)
    if not grid_path.exists():
        raise RuntimeError(f"Missing grid metadata {grid_path}; run download first.")
    grid = json.loads(grid_path.read_text(encoding="utf-8"))

    if smoke:
        scenarios = [SMOKE_SSP_SCENARIO]
        hist_fetch_years = list(range(SMOKE_HIST_YEARS[0], SMOKE_HIST_YEARS[1] + 1))
        hist_base_years = list(range(SMOKE_HIST_YEARS[0] + 1, SMOKE_HIST_YEARS[1] + 1))
        ssp_fetch_years = list(range(SMOKE_SSP_YEARS[0], SMOKE_SSP_YEARS[1] + 1))
        ssp_eval_years = [2050]
        min_models = 1
        baseline_label = f"{hist_base_years[0]}-{hist_base_years[-1]}"
    else:
        scenarios = list(SCENARIOS)
        hist_fetch_years = list(range(HIST_FETCH_START, HIST_END + 1))
        hist_base_years = list(range(HIST_START, HIST_END + 1))
        ssp_fetch_years = list(range(SSP_START, SSP_END + 1))
        ssp_eval_years = list(range(SSP_START, SSP_END + 1))
        min_models = MIN_COMPLETE_MODELS
        baseline_label = f"{HIST_START}-{HIST_END}"

    complete_models, missing_counts = _find_complete_models(
        cache_dir, models, scenarios, hist_fetch_years, ssp_fetch_years
    )
    if missing_counts:
        skipped_str = ", ".join(f"{m} ({c} missing)" for m, c in missing_counts.items())
        print(f"  incomplete models excluded: {skipped_str}", flush=True)
    if len(complete_models) < min_models:
        raise RuntimeError(
            f"Need at least {min_models} complete model(s) to finalize, found {len(complete_models)}: "
            f"{complete_models}. Missing: {missing_counts}"
        )
    print(f"  finalizing with {len(complete_models)} model(s): {', '.join(complete_models)}", flush=True)

    windows_meta = {str(y): f"{a}-{b}" for y in HORIZON_YEARS for a, b in [pt.centered_window(y)]}
    baseline_out: dict[str, dict[str, list]] = {}
    variables_out: dict[str, dict[str, dict[str, dict[str, list]]]] = {}

    nlat = len(grid["lat"])
    nlon = len(grid["lon"])
    null_grid = [[None] * nlon for _ in range(nlat)]

    for var in VARIABLES:
        digits = 2 if var == "tas" else 1
        baseline_out[var] = {}
        variables_out[var] = {}

        # Load monthly arrays once per (model, scen)
        model_hist_seasonal: dict[str, dict[str, dict[int, np.ndarray]]] = {}
        dec_2014: dict[str, dict[int, np.ndarray]] = {}
        model_ssp_seasonal: dict[tuple[str, str], dict[str, dict[int, np.ndarray]]] = {}

        for model in complete_models:
            h_monthly = {
                y: np.load(npy_cache_path(cache_dir, model, "historical", var, y)).astype(np.float64)
                for y in hist_fetch_years
            }
            model_hist_seasonal[model] = _compute_seasonal(h_monthly, var, hist_base_years)
            dec_2014[model] = {HIST_END: h_monthly[HIST_END][11]} if HIST_END in h_monthly else {}

            for scen in scenarios:
                s_monthly = {
                    y: np.load(npy_cache_path(cache_dir, model, scen, var, y)).astype(np.float64)
                    for y in ssp_fetch_years
                }
                model_ssp_seasonal[(model, scen)] = _compute_seasonal(
                    s_monthly, var, ssp_eval_years, prev_dec_by_year=dec_2014[model]
                )

        for season in SEASONS:
            model_baselines: dict[str, np.ndarray] = {}
            for model in complete_models:
                series = [model_hist_seasonal[model][season][y] for y in hist_base_years]
                model_baselines[model] = np.mean(np.stack(series, axis=0), axis=0)

            base_stack = np.stack([model_baselines[m] for m in complete_models], axis=0)
            baseline_out[var][season] = _to_json_grid(_nan_percentile_stack(base_stack, 50.0), digits)

            variables_out[var][season] = {}
            for scen in scenarios:
                med_horizons = []
                low_horizons = []
                high_horizons = []

                for ty in HORIZON_YEARS:
                    w0, w1 = pt.centered_window(ty)
                    per_model_win = []
                    for model in complete_models:
                        s_map = model_ssp_seasonal[(model, scen)][season]
                        base = model_baselines[model]
                        win_changes = [
                            s_map[y] - base for y in range(w0, w1 + 1) if y in s_map
                        ]
                        if win_changes:
                            per_model_win.append(np.mean(np.stack(win_changes, axis=0), axis=0))

                    if not per_model_win:
                        med_horizons.append(null_grid)
                        low_horizons.append(null_grid)
                        high_horizons.append(null_grid)
                    else:
                        stack = np.stack(per_model_win, axis=0)
                        med_horizons.append(_to_json_grid(_nan_percentile_stack(stack, 50.0), digits))
                        low_horizons.append(_to_json_grid(_nan_percentile_stack(stack, 10.0), digits))
                        high_horizons.append(_to_json_grid(_nan_percentile_stack(stack, 90.0), digits))

                variables_out[var][season][scen] = {
                    "median": med_horizons,
                    "low": low_horizons,
                    "high": high_horizons,
                }

    out = {
        "name": name,
        "bbox": [float(x) for x in bbox],
        "grid": grid,
        "models": complete_models,
        "baseline_period": baseline_label,
        "retrieved": time.strftime("%Y-%m-%d"),
        "source": "NASA NEX-GDDP-CMIP6 via NCCS THREDDS NCSS (bbox)",
        "catalog_url": f"{CATALOG_BASE}/catalog.html",
        "units": {"tas": "°C", "pr": "mm"},
        "horizons": {"years": HORIZON_YEARS, "windows": windows_meta},
        "baseline": baseline_out,
        "variables": variables_out,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"region-{name}.json"
    atomic_write_text(
        out_path, json.dumps(out, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    )
    size_kb = out_path.stat().st_size / 1024.0
    print(f"  wrote {out_path} ({size_kb:.1f} KB, grid {nlat}x{nlon})", flush=True)
    return out, out_path


def _print_smoke_summary(cache_dir: Path, name: str, out_path: Path) -> None:
    """Print per-cell JJA values from the smoke run for quick inspection."""
    grid = json.loads((cache_dir / "grid.json").read_text(encoding="utf-8"))
    lats, lons = grid["lat"], grid["lon"]
    print(f"\nSmoke JJA summary for {name!r} ({out_path}):", flush=True)
    for var, unit in (("tas", "°C"), ("pr", "mm")):
        m2050 = np.load(npy_cache_path(cache_dir, SMOKE_MODELS[0], SMOKE_SSP_SCENARIO, var, 2050))
        jja = np.mean(m2050[[5, 6, 7]], axis=0) if var == "tas" else np.sum(m2050[[5, 6, 7]], axis=0)
        print(f"  {SMOKE_MODELS[0]} {SMOKE_SSP_SCENARIO} 2050 JJA {var} ({unit}):", flush=True)
        for i, la in enumerate(lats):
            vals = ", ".join(f"{lons[j]}:{jja[i, j]:.3f}" for j in range(len(lons)))
            print(f"    lat={la}: {vals}", flush=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--name", help="region key (writes data/cmip6/region-<name>.json)")
    ap.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        metavar=("SOUTH", "WEST", "NORTH", "EAST"),
        help="bounding box: south west north east",
    )
    ap.add_argument("--models", nargs="+", help=f"CMIP6 models (default: {', '.join(DEFAULT_MODELS)})")
    ap.add_argument("--workers", type=int, default=4, help="concurrent NCSS requests (default 4, max 6)")
    ap.add_argument("--max-hours", type=float, default=None, help="stop gracefully after H hours")
    ap.add_argument("--smoke", action="store_true", help="quick 1-model 2012-2014 + 2049-2051 ssp585 check")
    ap.add_argument("--finalize-only", action="store_true", help="build JSON from cached .npy files only")
    ap.add_argument("--refresh", action="store_true", help="ignore cached .npy and catalog XMLs")
    ap.add_argument("--estimate", action="store_true", help="print task count and time estimate, then exit")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    a = parse_args(argv)
    workers = max(1, min(int(a.workers), 6))

    if a.smoke:
        name = a.name or "smoke"
        if not name.startswith("smoke"):
            name = f"smoke-{name}"
        bbox = validate_bbox(a.bbox if a.bbox is not None else SMOKE_BBOX)
        models = pt.parse_models(a.models) if a.models else list(SMOKE_MODELS)
    else:
        if not a.name:
            raise SystemExit("--name is required (unless --smoke is set)")
        if a.bbox is None:
            raise SystemExit("--bbox SOUTH WEST NORTH EAST is required (unless --smoke is set)")
        name = a.name
        bbox = validate_bbox(a.bbox)
        models = pt.parse_models(a.models)

    cache_dir = REGION_CACHE_ROOT / name

    if a.estimate:
        total = count_all_expected_tasks(models, smoke=a.smoke)
        est_sec = total * ESTIMATE_SEC_PER_TASK / workers
        cached = 0
        if cache_dir.is_dir():
            cached = sum(1 for _ in cache_dir.glob("*.npy"))
        rem_sec = max(0, total - cached) * ESTIMATE_SEC_PER_TASK / workers
        print(
            f"Estimate for region={name!r} bbox={list(bbox)} models={len(models)} ({', '.join(models)}) "
            f"workers={workers}:\n"
            f"  total tasks: {total} ({cached} cached, {max(0, total - cached)} remaining)\n"
            f"  full time (~{ESTIMATE_SEC_PER_TASK:.0f}s/task / {workers} workers): "
            f"{est_sec / 3600.0:.1f} h ({_format_duration(est_sec)})\n"
            f"  remaining time: {rem_sec / 3600.0:.1f} h ({_format_duration(rem_sec)})"
        )
        return 0

    if not a.finalize_only:
        finished_all, incomplete = run_downloads(
            name=name,
            bbox=bbox,
            models=models,
            workers=workers,
            cache_dir=cache_dir,
            smoke=a.smoke,
            refresh=a.refresh,
            max_hours=a.max_hours,
        )
        if not finished_all:
            print(
                f"Stopped before finishing all tasks (incomplete models so far: {sorted(incomplete)}). "
                f"Re-run the same command to resume.",
                flush=True,
            )
            return 0

    _, out_path = finalize_region(
        name=name,
        bbox=bbox,
        models=models,
        cache_dir=cache_dir,
        out_dir=OUT_DIR,
        smoke=a.smoke,
    )
    if a.smoke:
        _print_smoke_summary(cache_dir, name, out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
