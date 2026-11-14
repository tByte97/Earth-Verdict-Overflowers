"""NASA GES DISC Giovanni Time Series API adapter."""
from __future__ import annotations

import os
from pathlib import Path

from .cache import build_url, get_text
from .errors import SourceUnavailable

GIOVANNI_URL = "https://api.giovanni.earthdata.nasa.gov"

# key -> (Giovanni variable ID, multiplier to target units, target units, description)
GIOVANNI_VARS = {
    "precip_gpm": ("GPM_3IMERGM_07_precipitation", 24, "mm/day", "GPM IMERG precipitation (satellite + gauges), 0.1 deg"),
    "evap_gldas": ("GLDAS_NOAH025_M_2_1_Evap_tavg", 86400, "mm/day", "Land evapotranspiration, GLDAS Noah 2.1, 0.25 deg"),
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


def fetch_monthly(
    variable: str,
    lat: float,
    lon: float,
    start_year: int,
    end_year: int,
) -> dict:
    """Fetch a monthly point time series from NASA Giovanni."""
    if variable in GIOVANNI_VARS:
        var_id, factor, units, _ = GIOVANNI_VARS[variable]
    else:
        matched = [spec for spec in GIOVANNI_VARS.values() if spec[0] == variable]
        if not matched:
            raise ValueError(f"unknown Giovanni variable '{variable}'")
        var_id, factor, units, _ = matched[0]

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
