"""NOAA NCEI GSOM monthly and GHCN-Daily station adapter."""
from __future__ import annotations

import calendar
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import contextvars
from dataclasses import dataclass
import math
import time

from .cache import build_url, get_json

SEARCH_URL = "https://www.ncei.noaa.gov/access/services/search/v1/data"
DATA_URL = "https://www.ncei.noaa.gov/access/services/data/v1"
MIN_COVERAGE = 0.9
MIN_TEMP_DAYS = 25
DAILY_WORKERS = 6
DAILY_BUDGET_S = 45.0
VALID_ELEMENTS = frozenset({"TAVG", "TMAX", "TMIN", "PRCP"})
DAILY_FALLBACK_ELEMENTS = frozenset({"TAVG", "TMAX", "TMIN"})


@dataclass(frozen=True)
class StationSeries:
    id: str
    name: str
    lat: float
    lon: float
    distance_km: float
    element: str                    # "TAVG" | "TMAX" | "TMIN" | "PRCP"
    start: str                      # "YYYY-01"
    monthly: list[float | None]
    method: str                     # "gsom" or "ghcnd-daily-mean" or "ghcnd-daily-sum"
    coverage: float                 # share of months with data, 0..1
    url: str


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometers between two WGS84 points."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def _daily_monthly_series(
    station_id: str,
    element: str,
    start_year: int,
    end_year: int,
) -> tuple[list[float | None], str] | None:
    """Aggregate GHCN-Daily values into monthly means/sums without splicing with GSOM.

    Fetches per-year daily summaries concurrently (up to DAILY_WORKERS) within a shared
    overall DAILY_BUDGET_S deadline; returns None if the budget expires before completion.
    """
    years = list(range(start_year, end_year + 1))

    def _fetch_year(year: int) -> list[dict]:
        return get_json(
            DATA_URL,
            {
                "dataset": "daily-summaries",
                "stations": station_id,
                "startDate": f"{year}-01-01",
                "endDate": f"{year}-12-31",
                "dataTypes": element,
                "format": "json",
                "units": "metric",
            },
        )

    results_by_year: dict[int, list[dict]] = {}
    if years:
        pool = ThreadPoolExecutor(max_workers=min(DAILY_WORKERS, len(years)))
        futures = {
            pool.submit(contextvars.copy_context().run, _fetch_year, year): year
            for year in years
        }
        pending = set(futures)
        deadline = time.monotonic() + DAILY_BUDGET_S
        try:
            while pending:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                done, pending = wait(pending, timeout=remaining, return_when=FIRST_COMPLETED)
                if not done:
                    return None
                for fut in done:
                    results_by_year[futures[fut]] = fut.result()
        finally:
            # Never wait for stuck sockets on timeout/error; cancel queued tasks immediately.
            pool.shutdown(wait=not pending, cancel_futures=bool(pending))

    days_by_ym: dict[str, dict[str, float]] = {}
    for year in years:
        for row in results_by_year[year]:
            raw = row.get(element)
            date_str = row.get("DATE", "")
            if raw not in (None, "") and len(date_str) >= 7:
                days_by_ym.setdefault(date_str[:7], {})[date_str] = float(raw)

    monthly: list[float | None] = []
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            ym = f"{year}-{month:02d}"
            day_vals = days_by_ym.get(ym, {})
            if element == "PRCP":
                expected_days = calendar.monthrange(year, month)[1]
                val = round(sum(day_vals.values()), 2) if len(day_vals) == expected_days else None
            else:
                val = (
                    round(sum(day_vals.values()) / len(day_vals), 2)
                    if len(day_vals) >= MIN_TEMP_DAYS
                    else None
                )
            monthly.append(val)

    url = build_url(
        DATA_URL,
        {
            "dataset": "daily-summaries",
            "stations": station_id,
            "startDate": f"{start_year}-01-01",
            "endDate": f"{end_year}-12-31",
            "dataTypes": element,
            "format": "json",
            "units": "metric",
        },
    )
    return monthly, url


def best_station(
    lat: float,
    lon: float,
    element: str,
    start_year: int,
    end_year: int,
    *,
    max_km: float = 50,
    candidates: int = 5,
) -> StationSeries | None:
    """Find the best nearby NOAA station for `element` over [start_year, end_year]."""
    elem = element.upper()
    if elem not in VALID_ELEMENTS:
        raise ValueError(f"unsupported NOAA element: {element}")

    if max_km <= 50:
        dlat, dlon = 0.7, 1.0
    else:
        dlat = max(0.7, max_km / 111.0 + 0.1)
        dlon = max(1.0, max_km / (111.0 * max(math.cos(math.radians(lat)), 0.2)) + 0.1)

    bbox = f"{round(lat + dlat, 4)},{round(lon - dlon, 4)},{round(lat - dlat, 4)},{round(lon + dlon, 4)}"
    found = get_json(
        SEARCH_URL,
        {
            "dataset": "global-summary-of-the-month",
            "bbox": bbox,
            "startDate": f"{start_year}-01-01",
            "endDate": f"{end_year}-12-31",
            "limit": 20,
        },
    )

    seen_ids: set[str] = set()
    cands: list[tuple[float, str, str, float, float]] = []
    for item in found.get("results", []):
        stations = item.get("stations") or []
        points = item.get("boundingPoints") or []
        if not stations or not points:
            continue
        stn = stations[0]
        sid = stn["id"]
        if sid in seen_ids:
            continue
        coords = points[0].get("coordinates") or []
        if len(coords) < 2:
            continue
        lon_s, lat_s = float(coords[0]), float(coords[1])
        dist = haversine_km(lat, lon, lat_s, lon_s)
        if dist <= max_km:
            seen_ids.add(sid)
            cands.append((dist, sid, stn["name"], lat_s, lon_s))

    if not cands:
        return None
    cands.sort(key=lambda item: item[0])

    month_strs = [
        f"{year}-{month:02d}"
        for year in range(start_year, end_year + 1)
        for month in range(1, 13)
    ]
    total_months = len(month_strs)

    best_pick: tuple[int, float, str, str, float, float, list[float | None], str] | None = None
    for dist, sid, name, lat_s, lon_s in cands[:candidates]:
        gsom_params = {
            "dataset": "global-summary-of-the-month",
            "stations": sid,
            "startDate": f"{start_year}-01-01",
            "endDate": f"{end_year}-12-31",
            "dataTypes": elem,
            "format": "json",
            "units": "metric",
        }
        rows = get_json(DATA_URL, gsom_params)
        by_month = {row["DATE"]: row for row in rows if "DATE" in row}
        monthly = [
            (
                round(float(by_month[m][elem]), 2)
                if m in by_month and by_month[m].get(elem) not in (None, "")
                else None
            )
            for m in month_strs
        ]
        covered = sum(v is not None for v in monthly)
        if best_pick is None or covered > best_pick[0]:
            best_pick = (
                covered,
                dist,
                sid,
                name,
                lat_s,
                lon_s,
                monthly,
                build_url(DATA_URL, gsom_params),
            )

    assert best_pick is not None
    covered, dist, sid, name, lat_s, lon_s, monthly, data_url = best_pick
    method = "gsom"
    coverage = covered / total_months if total_months else 0.0

    # Replace the entire series with GHCN-Daily (never splice) if GSOM coverage < 90%.
    # Not for PRCP: a monthly total needs every day, so daily data recovers no months
    # (Lviv: 292 vs 293 of 540) while costing one request per year (~75 s on first call).
    if coverage < MIN_COVERAGE and elem in DAILY_FALLBACK_ELEMENTS:
        # None = the daily download ran out of its time budget: keep the monthly summary we
        # already have (the years fetched so far are cached, so the next request is quicker).
        daily = _daily_monthly_series(sid, elem, start_year, end_year)
        daily_monthly, daily_url = daily if daily is not None else ([], "")
        daily_covered = sum(v is not None for v in daily_monthly)
        if daily is not None and daily_covered > covered:
            monthly = daily_monthly
            covered = daily_covered
            coverage = covered / total_months if total_months else 0.0
            method = "ghcnd-daily-sum" if elem == "PRCP" else "ghcnd-daily-mean"
            data_url = daily_url

    return StationSeries(
        id=sid,
        name=name,
        lat=lat_s,
        lon=lon_s,
        distance_km=round(dist, 2),
        element=elem,
        start=f"{start_year}-01",
        monthly=monthly,
        method=method,
        coverage=round(coverage, 4),
        url=data_url,
    )
