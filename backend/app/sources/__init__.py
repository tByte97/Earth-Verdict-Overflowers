"""External climate data source adapters."""
from __future__ import annotations

from . import cache, cag, errors, geocode, giovanni, noaa, power
from .cache import get_json, get_text, source_name
from .cag import CAG_REGIONS, CAG_SEASONS, fetch_cag
from .errors import SourceUnavailable
from .geocode import search_places
from .giovanni import GIOVANNI_VARS
from .giovanni import fetch_monthly as fetch_giovanni_monthly
from .noaa import StationSeries, best_station
from .power import PowerMonthly
from .power import fetch_monthly as fetch_power_monthly

__all__ = [
    "CAG_REGIONS",
    "CAG_SEASONS",
    "GIOVANNI_VARS",
    "PowerMonthly",
    "SourceUnavailable",
    "StationSeries",
    "best_station",
    "cache",
    "cag",
    "errors",
    "fetch_cag",
    "fetch_giovanni_monthly",
    "fetch_power_monthly",
    "geocode",
    "get_json",
    "get_text",
    "giovanni",
    "noaa",
    "power",
    "search_places",
    "source_name",
]
