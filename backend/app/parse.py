"""Free-text claim -> check parameters, with Gemini.

The model only picks from fixed lists (variable ids, seasons, regions, directions) and copies
years from the claim. The code validates every field against the catalog, fills gaps with the
variable's full period, and finds the place with the normal geocoder. The user sees the result
in the form and confirms it before any check runs.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import OrderedDict
from typing import Optional

from . import llm
from .catalog import load_variables
from .check import REGIONS, CheckError
from .models import CaseSpec, ParsedClaim, Place

SEASONS = ("year", "DJF", "MAM", "JJA", "SON")
DIRECTIONS = ("increase", "decrease", "change")
CACHE_SIZE = 256
_cache: "OrderedDict[str, ParsedClaim]" = OrderedDict()


def _system() -> str:
    variables = "\n".join(f"- {v.id}: {v.label} ({v.units}), years {v.first_year}-{v.last_year}. {v.definition}"
                          for v in load_variables().values())
    regions = ", ".join(REGIONS)
    return f"""You turn a claim about climate or weather into check parameters. The claim may be in any language.
Reply with one JSON object only, with these keys:
"variable_id": one id from the list below, or null if no variable fits the claim.
"place": the town, city or country the claim names, in English (e.g. "Kyiv"), or null.
"region": for variable global_temp only, one of: {regions}; null otherwise.
"season": "year", "DJF" (winter), "MAM" (spring), "JJA" (summer) or "SON" (autumn).
"start_year", "end_year": integers only if the claim states them (e.g. "after 1998" gives start_year 1998), else null.
"claim_direction": "increase", "decrease" or "change".
"notes": a list of short English sentences on anything you had to assume.

Rules:
- Claims about the whole planet, a continent or global warming use global_temp; "planet" or no place means region "globe".
- "warmer/hotter" is air_temp increase; "colder" is air_temp decrease; "rainier/wetter" is precip increase; "drier" or "rains less" is precip decrease; snow claims use snow_depth. Prefer air_temp and precip unless the claim names days, nights, satellites, soil, sunlight or evaporation.
- "stopped", "paused" or "no longer rising" means decrease (the claim says it is not rising), and add a note: "Stopped is checked as not rising: a clear rise refutes it."
- If the claim gives no direction, use "change".
- Never invent years, places or variables that the claim does not suggest.

Variables:
{variables}"""


def _fallback_place() -> Place:
    name, lat, lon = REGIONS["globe"]
    return Place(place_id="region:globe", name=name, lat=lat, lon=lon)


def _year(value) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _read(text: str) -> dict:
    """The model's reply as a dict; tolerate a ```json fence around it."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise CheckError("cannot_parse", "Could not read the claim. Set the parameters below by hand.")
    try:
        data = json.loads(m.group(0))
    except ValueError as exc:
        raise CheckError("cannot_parse", "Could not read the claim. Set the parameters below by hand.") from exc
    if not isinstance(data, dict):
        raise CheckError("cannot_parse", "Could not read the claim. Set the parameters below by hand.")
    return data


def _geocode(query: str) -> Optional[Place]:
    from .sources import SourceUnavailable, geocode
    try:
        found = geocode.search_places(query)
    except SourceUnavailable:
        return None
    if not found:
        return None
    p = found[0]
    return Place(place_id=p["place_id"], name=p["name"], lat=p["lat"], lon=p["lon"])


def build(text: str, data: dict, model: str) -> ParsedClaim:
    """Validate the model's fields against the catalog and turn them into a CaseSpec."""
    variables = load_variables()
    vid = data.get("variable_id")
    if vid not in variables:
        raise CheckError("cannot_parse", "This claim is not about a variable Earth Verdict can check. "
                                         "Choose one of the variables below.")
    var = variables[vid]
    notes = [n.strip() for n in data.get("notes") or [] if isinstance(n, str) and n.strip()][:4]

    season = data.get("season") if data.get("season") in SEASONS else "year"
    direction = data.get("claim_direction") if data.get("claim_direction") in DIRECTIONS else "change"

    start, end = _year(data.get("start_year")), _year(data.get("end_year"))
    if start is None or start < var.first_year:
        if start is not None:
            notes.append(f"{var.label} data start in {var.first_year}, so the check starts there.")
        start = var.first_year
    if end is None or end > var.last_year:
        if end is not None:
            notes.append(f"{var.label} data end in {var.last_year}, so the check ends there.")
        end = var.last_year
    if start > end:
        start, end = var.first_year, var.last_year
        notes.append("The years in the claim did not form a period, so the full record is used.")

    query = data.get("place") if isinstance(data.get("place"), str) and data.get("place").strip() else None
    if vid == "global_temp":
        key = data.get("region") if data.get("region") in REGIONS else "globe"
        name, lat, lon = REGIONS[key]
        place, found = Place(place_id=f"region:{key}", name=name, lat=lat, lon=lon), True
    else:
        place = _geocode(query.strip()[:100]) if query else None
        found = place is not None
        if not found:
            place = _fallback_place()
            notes.append(f"Could not find “{query}”. Choose the place below." if query
                         else "The claim names no place. Choose one below.")

    spec = CaseSpec(claim_text=text, variable_id=vid, place=place, season=season,
                    start_year=start, end_year=end, claim_direction=direction)
    return ParsedClaim(spec=spec, place_found=found, place_query=query, notes=notes, model=model)


def parse_claim(text: str) -> ParsedClaim:
    text = " ".join(text.split())
    model = llm._model()
    ck = hashlib.sha256(json.dumps([text, model]).encode()).hexdigest()
    with llm._lock:
        if ck in _cache:
            _cache.move_to_end(ck)
            return _cache[ck]

    key = llm._api_key()
    if key is None:
        raise CheckError("llm_unavailable", "Reading claims is not configured on this server.")
    reply = None
    for attempt in range(2):          # one retry: the model service has short outages (HTTP 503)
        if not llm._rate_ok():
            raise CheckError("llm_unavailable", "Too many requests to the language model; try again in a minute.")
        try:
            reply = llm._call_gemini(key, model, f"CLAIM: {text}", system=_system(), json_out=True)
            break
        except llm._Busy as exc:
            raise CheckError("llm_unavailable", "The language model is busy.") from exc
        except CheckError as exc:
            if attempt == 1:
                raise CheckError("llm_unavailable", "The language model did not answer.") from exc

    result = build(text, _read(reply), model)
    with llm._lock:
        _cache[ck] = result
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return result
