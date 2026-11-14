#!/usr/bin/env python3
"""Збирає показові справи (CheckResult) з даних, викачаних tools/fetch_data.py.

Використовує статистичне ядро backend/app/stats та backend/app/verdict.

Запуск (з кореня репозиторію):
  backend/.venv/bin/python tools/build_cases.py --explore   # таблиця кандидатів
  backend/.venv/bin/python tools/build_cases.py             # data/cases/*.json + mock.json
"""
import argparse
import calendar
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))
from app.catalog import get_variable  # noqa: E402
from app.check import MainSeries, StationInput, assemble_result  # noqa: E402
from app.models import CaseSpec  # noqa: E402

DATA = ROOT / "data"
CASES = DATA / "cases"

# Тип станційного ряду у файлі fetch_data.py → метод у контракті
STATION_METHOD = {"gsom": "gsom", "ghcnd": "ghcnd-daily-mean"}


def load_city(key):
    return json.loads((DATA / f"{key}.json").read_text())


def build(city_key, variable_id, season, direction, claim, start=1981, end=2025, scenarios=None):
    """Справа з локально викачаних даних, тим самим кодом, що й API (app.check.assemble_result)."""
    city = load_city(city_key)
    var = get_variable(variable_id)
    spec = CaseSpec(claim_text=claim, variable_id=variable_id,
                    place=dict(place_id=f"city:{city_key}", name=city["name"], lat=city["lat"], lon=city["lon"]),
                    season=season, start_year=start, end_year=end, claim_direction=direction)
    m_start = city.get("months_start", "1981-01")
    lat, lon = city["lat"], city["lon"]
    main = MainSeries(
        monthly=city["power"]["series"][var.source_param], start=m_start,
        url=(f"https://power.larc.nasa.gov/api/temporal/monthly/point?parameters={var.source_param}&community=AG"
             f"&latitude={lat}&longitude={lon}&start=1981&end={end}&format=JSON"),
        retrieved_at=city["retrieved"])
    station = None
    st = city.get("station")
    if var.witness and st and var.witness in st.get("series", {}):
        method = "gsom"
        if var.witness == "TAVG" and st.get("tavg_source", "").startswith("ghcnd"):
            method = "ghcnd-daily-mean"
        dataset = "global-summary-of-the-month" if method == "gsom" else "daily-summaries"
        station = StationInput(
            id=st["id"], name=st["name"], lat=st["lat"], lon=st["lon"], distance_km=st["distance_km"],
            monthly=st["series"][var.witness], start=m_start, method=method,
            url=(f"https://www.ncei.noaa.gov/access/services/data/v1?dataset={dataset}&stations={st['id']}"
                 f"&dataTypes={var.witness}&units=metric&format=json"),
            retrieved_at=city["retrieved"])
    r = assemble_result(spec, var, main, station, scenarios=scenarios, stub=True)
    return r.model_dump(mode="json"), r


# ---------- сценарії: NASA NEX-GDDP-CMIP6 (#14) ----------

def cmip6_scenarios(city_key, variable_id, season):
    """Ансамбль CMIP6 з data/cmip6/<місто>.json (tools/fetch_cmip6.py); базу 1995–2014 бере assemble_result зі спостережень."""
    from cmip6_to_scenarios import load_cmip6_scenarios

    sc = load_cmip6_scenarios(city_key, variable_id=variable_id, season=season)
    sc.pop("baseline_value", None)
    meta = json.loads((DATA / "cmip6" / f"{city_key}.json").read_text())
    sc["provenance"] = [dict(
        what="Future scenarios", source="NASA NCCS", product=f"NEX-GDDP-CMIP6 v2.0, {len(meta['models'])} models, r1i1p1f1",
        url="https://ds.nccs.nasa.gov/thredds/catalog/AMES/NEX/GDDP-CMIP6/catalog.html",
        retrieved_at=meta.get("retrieved", "2026-11-14"), license="CC BY 4.0 (NASA NEX-GDDP-CMIP6)")]
    return sc


SHOWCASE = [
    # (файл, місто, змінна, сезон, напрямок твердження, текст, сценарії)
    ("kyiv-summer-heat", "kyiv", "air_temp", "JJA", "increase", "Summers in Kyiv are getting hotter", True),
    ("lviv-drier", "lviv", "precip", "year", "decrease", "Lviv is getting drier, it rains less every year", None),
    ("kyiv-winter-snow", "kyiv", "snow_depth", "DJF", "increase", "Kyiv winters have more snow now", None),
]

CANDIDATES = [(c, v, s, dr) for c in ("kyiv", "lviv", "odesa", "kharkiv", "warsaw")
              for v, s, dr in [("air_temp", "JJA", "increase"), ("air_temp", "DJF", "increase"),
                               ("precip", "year", "decrease"), ("precip", "JJA", "decrease"),
                               ("snow_depth", "DJF", "increase")]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--explore", action="store_true")
    a = ap.parse_args()
    if a.explore:
        print(f"{'місто':8} {'змінна':11} {'сезон':5} {'твердження':9} {'нахил/10р':>10} {'p':>7} {'вікна':>5} {'свідок':11} вердикт")
        for c, v, s, dr in CANDIDATES:
            r, m = build(c, v, s, dr, "explore")
            w = r["witness"]["agreement"] if r["witness"] else "no_station"
            print(f"{c:8} {v:11} {s:5} {dr:9} {r['sen']['slope_per_decade']:>10.3f} {r['mk']['p']:>7.4f} "
                  f"{r['robustness_summary']['significant']}/{r['robustness_summary']['total']:<3} {w:11} {r['verdict']} ({r['reason']})"
                  + (f", чекати {r['years_to_wait']}" if r["years_to_wait"] is not None else ""))
        return
    CASES.mkdir(parents=True, exist_ok=True)
    for i, (fname, c, v, s, dr, claim, scen) in enumerate(SHOWCASE):
        r, _ = build(c, v, s, dr, claim, scenarios=cmip6_scenarios(c, v, s) if scen else None)
        (CASES / f"{fname}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1))
        if i == 0:
            (CASES / "mock.json").write_text(json.dumps(r, ensure_ascii=False, indent=1))
        print(f"{fname}: {r['verdict']} ({r['reason']}), {r['sen']['slope_per_decade']:+.3f} {r['variable']['units']}/10 р.")


if __name__ == "__main__":
    main()
