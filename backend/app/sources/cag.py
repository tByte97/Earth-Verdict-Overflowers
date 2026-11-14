"""NOAA NCEI Climate at a Glance regional temperature anomaly adapter."""
from __future__ import annotations

from .cache import get_json

CAG_BASE_URL = "https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/global/time-series"
CAG_REGIONS = [
    "globe",
    "europe",
    "asia",
    "africa",
    "northAmerica",
    "southAmerica",
    "oceania",
    "arctic",
]
_REGION_MAP = {region.lower(): region for region in CAG_REGIONS}

# (span_months, end_month)
CAG_SEASONS = {
    "year": (12, 12),
    "djf": (3, 2),
    "mam": (3, 5),
    "jja": (3, 8),
    "son": (3, 11),
}
CAG_END_YEAR = 2026


def fetch_cag(region: str, season: str | int) -> dict:
    """Fetch NOAA Climate at a Glance land+ocean temperature anomalies (1901-2000 base).

    `season` is year/DJF/MAM/JJA/SON or a month number 1..12.
    """
    canonical_region = _REGION_MAP.get(region.strip().lower())
    if canonical_region is None:
        raise ValueError(f"unsupported CAG region '{region}'; expected one of {CAG_REGIONS}")

    if isinstance(season, int):
        if not 1 <= season <= 12:
            raise ValueError(f"unsupported CAG month {season}")
        span, month = 1, season
    else:
        season_key = season.strip().lower()
        if season_key not in CAG_SEASONS:
            raise ValueError(f"unsupported CAG season '{season}'; expected one of {list(CAG_SEASONS)}")
        span, month = CAG_SEASONS[season_key]
    url = f"{CAG_BASE_URL}/{canonical_region}/land_ocean/{span}/{month}/1850-{CAG_END_YEAR}/data.json"
    data = get_json(url)

    raw_data = data.get("data", {})
    years = sorted(raw_data, key=int)
    anomalies: list[float | None] = []
    for year in years:
        entry = raw_data[year]
        val = entry.get("departure") if isinstance(entry, dict) else entry
        anomalies.append(float(val) if val is not None else None)

    return {
        "years": [int(y) for y in years],
        "anomaly": anomalies,
        "base_period": "1901-2000",
        "units": "°C",
        "url": url,
    }
