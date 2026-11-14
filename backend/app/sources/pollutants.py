"""Pollutant site + surrounding control ring fetcher (Giovanni) and NOAA global CO2 fetcher."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import math
from typing import Optional

from ..catalog import get_compound
from . import giovanni
from .cache import get_text

NOAA_CO2_URL = "https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_mm_gl.txt"
NOAA_CO2_MAX_AGE_S = 7 * 24 * 3600  # NOAA adds a month roughly monthly
_EARTH_RADIUS_KM = 6371.0
_DEFAULT_RING_KM = 120.0
_MIN_CONTROL_POINTS = 5
_MAX_WORKERS = 4
_DIRECTIONS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def control_ring_points(
    lat: float,
    lon: float,
    radius_km: float = _DEFAULT_RING_KM,
) -> list[tuple[str, float, float]]:
    """Return 8 compass points (N, NE, ..., NW) on a circle of ``radius_km`` around (lat, lon)."""
    d = radius_km / _EARTH_RADIUS_KM
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    cos_d = math.cos(d)
    sin_d = math.sin(d)
    cos_lat1 = math.cos(lat1)
    sin_lat1 = math.sin(lat1)

    points: list[tuple[str, float, float]] = []
    for idx, label in enumerate(_DIRECTIONS):
        bearing = math.radians(idx * 45.0)
        lat2 = math.asin(sin_lat1 * cos_d + cos_lat1 * sin_d * math.cos(bearing))
        lon2 = lon1 + math.atan2(
            math.sin(bearing) * sin_d * cos_lat1,
            cos_d - sin_lat1 * math.sin(lat2),
        )
        lat_deg = max(-89.9, min(89.9, math.degrees(lat2)))
        lon_deg = ((math.degrees(lon2) + 180.0) % 360.0) - 180.0
        points.append((label, round(lat_deg, 4), round(lon_deg, 4)))
    return points


def fetch_site_and_control(
    compound_id: str,
    lat: float,
    lon: float,
    start_year: int,
    end_year: int,
    *,
    include_control: bool = True,
    min_control_points: int = _MIN_CONTROL_POINTS,
    radius_km: float = _DEFAULT_RING_KM,
    max_workers: int = _MAX_WORKERS,
) -> dict:
    """Fetch monthly satellite series for the site and an 8-point ~120 km control ring.

    Giovanni's ``/timeseries`` REST endpoint only accepts single ``[lat,lon]`` point
    queries (bbox / area-average queries return 400 "Location parameter is invalid"),
    so site and each of the 8 ring points are fetched as cached point time series with
    at most 4 concurrent requests. Ring points sit at different levels, so each month's control
    value is the mean of the points' deviations from their own long-term mean, plus the ring's
    overall mean: a cloudy month that drops one point no longer shifts the series. Months with
    fewer than ``min_control_points`` (5/8) valid control points yield ``None``.
    """
    compound = get_compound(compound_id)
    if compound is None:
        raise ValueError(f"unknown compound '{compound_id}'")
    if start_year > end_year:
        raise ValueError(f"start_year ({start_year}) exceeds end_year ({end_year})")

    prec = max(4, compound.decimals + 2)
    coords: list[tuple[str, float, float]] = [("site", round(lat, 4), round(lon, 4))]
    if include_control:
        coords.extend(control_ring_points(lat, lon, radius_km=radius_km))

    def _fetch_one(item: tuple[str, float, float]) -> dict:
        _, p_lat, p_lon = item
        return giovanni.fetch_daily_as_monthly(
            compound.giovanni_id,
            p_lat,
            p_lon,
            start_year,
            end_year,
            min_valid_days=compound.min_valid_days,
            decimals=prec,
        )

    workers = min(max_workers, len(coords))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(_fetch_one, coords))

    site_res = results[0]
    month_strs = [
        f"{year}-{month:02d}"
        for year in range(start_year, end_year + 1)
        for month in range(1, 13)
    ]

    control_series: Optional[list[Optional[float]]] = None
    control_points: list[dict] = []
    control_urls: list[str] = []
    if include_control:
        ring_results = results[1:]
        point_means: list[Optional[float]] = []
        for r in ring_results:
            vals = [v for v in r["monthly"] if v is not None]
            point_means.append(sum(vals) / len(vals) if vals else None)
        known = [m for m in point_means if m is not None]
        ring_level = sum(known) / len(known) if known else 0.0
        control_series = []
        for idx in range(len(month_strs)):
            devs = [
                r["monthly"][idx] - mean
                for r, mean in zip(ring_results, point_means)
                if mean is not None and r["monthly"][idx] is not None
            ]
            if len(devs) >= min_control_points:
                control_series.append(round(ring_level + sum(devs) / len(devs), prec))
            else:
                control_series.append(None)
        for (label, p_lat, p_lon), r in zip(coords[1:], ring_results):
            control_points.append({"direction": label, "lat": p_lat, "lon": p_lon, "cell": r["cell"]})
            control_urls.append(r["url"])

    return {
        "compound_id": compound.id,
        "giovanni_id": compound.giovanni_id,
        "units": compound.units,
        "start": f"{start_year}-01",
        "months": month_strs,
        "site": site_res["monthly"],
        "control": control_series,
        "site_cell": site_res["cell"],
        "control_points": control_points,
        "url": site_res["url"],
        "control_urls": control_urls,
        "doi": site_res.get("doi"),
        "request_strategy": "point_timeseries",
    }


def _validate_noaa_co2(text: str) -> None:
    if "year" not in text or "average" not in text:
        raise ValueError("unexpected NOAA GML CO2 response")


def fetch_noaa_co2() -> dict:
    """Fetch global monthly mean CO2 (ppm) from NOAA Global Monitoring Laboratory."""
    text = get_text(NOAA_CO2_URL, ext="txt", validate=_validate_noaa_co2, max_age_s=NOAA_CO2_MAX_AGE_S)
    months: list[str] = []
    values: list[Optional[float]] = []

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) < 4:
            continue
        year = int(parts[0])
        month = int(parts[1])
        avg = float(parts[3])
        months.append(f"{year:04d}-{month:02d}")
        values.append(None if avg < 0 else round(avg, 2))

    return {
        "months": months,
        "values": values,
        "url": NOAA_CO2_URL,
    }
