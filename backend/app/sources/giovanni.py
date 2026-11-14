"""NASA GES DISC Giovanni Time Series API adapter."""
from __future__ import annotations

from collections import defaultdict
import os
from pathlib import Path

from .cache import build_url, get_text
from .errors import SourceUnavailable

GIOVANNI_URL = "https://api.giovanni.earthdata.nasa.gov"

# key -> (Giovanni variable ID, multiplier to target units, target units, description)
GIOVANNI_VARS = {
    "precip_gpm": ("GPM_3IMERGM_07_precipitation", 24, "mm/day", "GPM IMERG precipitation (satellite + gauges), 0.1 deg"),
    "evap_gldas": ("GLDAS_NOAH025_M_2_1_Evap_tavg", 86400, "mm/day", "Land evapotranspiration, GLDAS Noah 2.1, 0.25 deg"),
    "no2": ("OMNO2d_003_ColumnAmountNO2TropCloudScreened", 1.0e-15, "10¹⁵ molecules/cm²", "OMI tropospheric NO2 column (cloud-screened), 0.25 deg"),
    "so2": ("OMSO2e_003_ColumnAmountSO2", 1.0, "DU", "OMI planetary boundary layer SO2 column, 0.25 deg"),
    "aod": ("M2T1NXAER_5_12_4_TOTEXTTAU", 1.0, "AOD", "MERRA-2 total aerosol extinction AOT 550 nm, 0.5x0.625 deg"),
    "co2": ("OCO2_GEOS_L3CO2_DAY_10r_XCO2", 1.0e6, "ppm", "OCO-2 GEOS Level 3 column XCO2, 0.5x0.625 deg"),
}


def _earthdata_token() -> str:
    tok = os.environ.get("EARTHDATA_TOKEN", "").strip()
    if tok:
        return tok
    token_file = Path.home() / ".config" / "earthdata" / "token"
    if token_file.exists():
        tok = token_file.read_text(encoding="utf-8").strip()
        if tok:
            return tok
    raise SourceUnavailable("giovanni", f"missing Earthdata token (set EARTHDATA_TOKEN or create {token_file})")


def _validate_csv(text: str) -> None:
    if "Timestamp (UTC),Data" not in text:
        raise ValueError("unexpected Giovanni CSV response")


def _resolve_var(variable: str) -> tuple[str, float, str, str]:
    if variable in GIOVANNI_VARS:
        return GIOVANNI_VARS[variable]
    matched = [spec for spec in GIOVANNI_VARS.values() if spec[0] == variable]
    if not matched:
        raise ValueError(f"unknown Giovanni variable '{variable}'")
    return matched[0]


def _fetch_timeseries_csv(
    var_id: str,
    lat: float,
    lon: float,
    start_year: int,
    end_year: int,
) -> tuple[dict[str, str], str, str, float, float]:
    token = _earthdata_token()
    lat_r = round(lat, 4)
    lon_r = round(lon, 4)
    endpoint = f"{GIOVANNI_URL}/timeseries"
    params = {
        "data": var_id,
        "location": f"[{lat_r},{lon_r}]",
        "time": f"{start_year}-01-01T00:00:00/{end_year}-12-31T23:59:59",
    }
    url = build_url(endpoint, params)
    csv_text = get_text(
        endpoint,
        params,
        headers={"Authorization": f"Bearer {token}"},
        ext="csv",
        validate=_validate_csv,
    )
    head, body = csv_text.split("Timestamp (UTC),Data", 1)
    meta = dict(line.split(",", 1) for line in head.strip().splitlines() if "," in line)
    return meta, body, url, lat_r, lon_r


def fetch_monthly(
    variable: str,
    lat: float,
    lon: float,
    start_year: int,
    end_year: int,
) -> dict:
    """Fetch a monthly point time series from NASA Giovanni."""
    var_id, factor, units, _ = _resolve_var(variable)
    meta, body, url, lat_r, lon_r = _fetch_timeseries_csv(var_id, lat, lon, start_year, end_year)
    undef = float(meta.get("undef", "-9999.9"))

    values: dict[str, float] = {}
    for line in body.strip().splitlines():
        if "," not in line:
            continue
        ts, raw = line.split(",", 1)
        val_str = raw.strip()
        if val_str not in ("", "undef"):
            fval = float(val_str)
            if fval != undef:
                values[ts[:7]] = round(fval * factor, 4)

    month_strs = [
        f"{year}-{month:02d}"
        for year in range(start_year, end_year + 1)
        for month in range(1, 13)
    ]
    return {
        "variable": var_id,
        "units": units,
        "source_units": meta.get("unit"),
        "doi": meta.get("doi"),
        "cell": [float(meta.get("lat", lat_r)), float(meta.get("lon", lon_r))],
        "start": f"{start_year}-01",
        "monthly": [values.get(m) for m in month_strs],
        "url": url,
    }


def fetch_daily_as_monthly(
    variable: str,
    lat: float,
    lon: float,
    start_year: int,
    end_year: int,
    *,
    min_valid_days: int = 10,
    decimals: int = 4,
) -> dict:
    """Fetch daily/hourly Giovanni series and aggregate to monthly means requiring >= min_valid_days."""
    var_id, factor, units, _ = _resolve_var(variable)
    meta, body, url, lat_r, lon_r = _fetch_timeseries_csv(var_id, lat, lon, start_year, end_year)
    undef = float(meta.get("undef", "-9999.9"))

    by_month_vals: dict[str, list[float]] = defaultdict(list)
    by_month_days: dict[str, set[str]] = defaultdict(set)
    for line in body.strip().splitlines():
        if "," not in line:
            continue
        ts, raw = line.split(",", 1)
        val_str = raw.strip()
        if val_str not in ("", "undef"):
            fval = float(val_str)
            if fval != undef:
                ym = ts[:7]
                by_month_vals[ym].append(fval * factor)
                by_month_days[ym].add(ts[:10])

    values: dict[str, float] = {}
    valid_days: dict[str, int] = {}
    for ym, vals in by_month_vals.items():
        n_days = len(by_month_days[ym])
        valid_days[ym] = n_days
        if n_days >= min_valid_days:
            values[ym] = round(sum(vals) / len(vals), decimals)

    month_strs = [
        f"{year}-{month:02d}"
        for year in range(start_year, end_year + 1)
        for month in range(1, 13)
    ]
    return {
        "variable": var_id,
        "units": units,
        "source_units": meta.get("unit"),
        "doi": meta.get("doi"),
        "cell": [float(meta.get("lat", lat_r)), float(meta.get("lon", lon_r))],
        "start": f"{start_year}-01",
        "monthly": [values.get(m) for m in month_strs],
        "valid_days": [valid_days.get(m, 0) for m in month_strs],
        "url": url,
    }
