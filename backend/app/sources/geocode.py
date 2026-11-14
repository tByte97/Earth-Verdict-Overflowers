"""Open-Meteo geocoding adapter with capital/admin ranking and Cyrillic support."""
from __future__ import annotations

from .cache import get_json
from .errors import SourceUnavailable

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"

# Open-Meteo dropped some legacy exonyms (e.g., "Kiev" no longer resolves to Kyiv).
_EXONYM_ALIASES = {
    "kiev": "Kyiv",
    "odessa": "Odesa",
    "lvov": "Lviv",
    "kharkov": "Kharkiv",
    "nikolaev": "Mykolaiv",
}


def _has_cyrillic(text: str) -> bool:
    return any("\u0400" <= ch <= "\u04ff" for ch in text)


def _rank_key(item: dict) -> tuple[int, int]:
    fc = (item.get("feature_code") or "").upper()
    if fc == "PPLC":
        tier = 0
    elif fc.startswith("PPLA"):
        tier = 1
    else:
        tier = 2
    pop = item.get("population") or 0
    return (tier, -int(pop))


def _format_place(item: dict) -> dict:
    name = item["name"]
    country = item.get("country")
    full_name = f"{name}, {country}" if country else name
    return {
        "place_id": f"om:{item['id']}",
        "name": full_name,
        "lat": float(item["latitude"]),
        "lon": float(item["longitude"]),
        "country_code": item.get("country_code") or "",
        "admin1": item.get("admin1"),
        "population": item.get("population"),
        "feature_code": item.get("feature_code"),
    }


def search_places(query: str, *, count: int = 5, language: str = "en") -> list[dict]:
    """Search places via Open-Meteo geocoding, ranking capitals and admin seats first."""
    q = query.strip()
    if not q or count <= 0:
        return []

    req_count = 10 if count <= 10 else count
    merged: dict[int, dict] = {}

    def _collect(name: str, lang: str) -> None:
        resp = get_json(
            GEOCODE_URL,
            {"name": name, "count": req_count, "language": lang, "format": "json"},
        )
        for item in resp.get("results", []):
            item_id = item.get("id")
            if item_id is not None and item_id not in merged:
                merged[item_id] = item

    _collect(q, language)

    if _has_cyrillic(q) and language != "uk":
        _collect(q, "uk")

    alias = _EXONYM_ALIASES.get(q.casefold())
    if alias and not any((r.get("feature_code") or "").upper() in ("PPLC", "PPLA") for r in merged.values()):
        try:
            _collect(alias, language)
        except SourceUnavailable:
            # Do not fail an offline/cached primary query when the optional alias isn't cached.
            pass

    ranked = sorted(merged.values(), key=_rank_key)
    return [_format_place(item) for item in ranked[:count]]
