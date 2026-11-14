"""NASA POWER monthly point data source adapter."""
from __future__ import annotations

from dataclasses import dataclass

from .cache import build_url, get_json
from .errors import SourceUnavailable

POWER_URL = "https://power.larc.nasa.gov/api/temporal/monthly/point"
POWER_MAX_END_YEAR = 2025


@dataclass(frozen=True)
class PowerMonthly:
    start: str                              # "YYYY-01"
    series: dict[str, list[float | None]]   # param -> monthly values from `start`
    units: dict[str, str]
    grid_cell: tuple[float, float]          # (lon, lat) as returned in geometry
    url: str                                # request URL (no secrets)


def fetch_monthly(
    lat: float,
    lon: float,
    params: list[str],
    start_year: int,
    end_year: int,
) -> PowerMonthly:
    """Fetch monthly NASA POWER point time series for the requested parameters."""
    capped_end = min(end_year, POWER_MAX_END_YEAR)
    if start_year > capped_end:
        raise ValueError(f"start_year ({start_year}) exceeds capped end_year ({capped_end})")

    lat_r = round(lat, 4)
    lon_r = round(lon, 4)
    query = {
        "parameters": ",".join(params),
        "community": "AG",
        "latitude": lat_r,
        "longitude": lon_r,
        "start": start_year,
        "end": capped_end,
        "format": "JSON",
    }
    url = build_url(POWER_URL, query)
    data = get_json(POWER_URL, query)

    par = data.get("properties", {}).get("parameter", {})
    meta_params = data.get("parameters", {})
    coords = data.get("geometry", {}).get("coordinates", [])
    if len(coords) < 2:
        raise SourceUnavailable("power", "missing geometry coordinates in response")

    month_keys = [
        f"{year}{month:02d}"
        for year in range(start_year, capped_end + 1)
        for month in range(1, 13)
    ]

    series: dict[str, list[float | None]] = {}
    units: dict[str, str] = {}
    for param in params:
        param_data = par.get(param)
        if param_data is None:
            raise SourceUnavailable("power", f"missing parameter '{param}' in response")
        # Month "13" (annual mean) is excluded by iterating months 1..12; <= -900 means missing.
        series[param] = [
            None if (val := param_data.get(mk)) is None or val <= -900 else round(float(val), 3)
            for mk in month_keys
        ]
        units[param] = meta_params.get(param, {}).get("units", "")

    return PowerMonthly(
        start=f"{start_year}-01",
        series=series,
        units=units,
        grid_cell=(float(coords[0]), float(coords[1])),
        url=url,
    )
