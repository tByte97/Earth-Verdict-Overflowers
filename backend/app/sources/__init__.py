"""External climate data source adapters."""
from __future__ import annotations

from . import cache, cag, errors, geocode, giovanni, noaa, pollutants, power
from .cache import get_json, get_text, source_name
from .cag import CAG_REGIONS, CAG_SEASONS, fetch_cag
from .errors import SourceUnavailable
from .geocode import search_places
from .giovanni import GIOVANNI_VARS
from .giovanni import fetch_daily_as_monthly as fetch_giovanni_daily_monthly
from .giovanni import fetch_monthly as fetch_giovanni_monthly
from .noaa import StationSeries, best_station
from .pollutants import NOAA_CO2_URL, control_ring_points, fetch_noaa_co2, fetch_site_and_control
from .power import PowerMonthly
from .power import fetch_monthly as fetch_power_monthly

__all__ = [
    "CAG_REGIONS",
    "CAG_SEASONS",
    "GIOVANNI_VARS",
    "NOAA_CO2_URL",
    "PowerMonthly",
    "SourceUnavailable",
    "StationSeries",
    "best_station",
    "cache",
    "cag",
    "control_ring_points",
    "errors",
    "fetch_cag",
    "fetch_giovanni_daily_monthly",
    "fetch_giovanni_monthly",
    "fetch_noaa_co2",
    "fetch_power_monthly",
    "fetch_site_and_control",
    "geocode",
    "get_json",
    "get_text",
    "giovanni",
    "noaa",
    "pollutants",
    "power",
    "search_places",
    "source_name",
]
