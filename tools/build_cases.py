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


# ---------- сценарії: стилізовані, поки немає CMIP6 (#14) ----------

def stylised_heat():
    years = [2015, 2030, 2050, 2070, 2100]
    paths = {"ssp126": ("The world cuts emissions fast", [0.45, 0.95, 1.3, 1.4, 1.4]),
             "ssp245": ("Roughly as now", [0.45, 1.05, 1.65, 2.15, 2.75]),
             "ssp585": ("Emissions keep growing", [0.45, 1.15, 2.1, 3.3, 5.1])}
    return dict(synthetic=True, source="Stylised curves for layout; will be replaced by NASA NEX-GDDP-CMIP6",
                baseline_period="1995-2014",
                note="These are climate-model scenarios, not a forecast. Which one happens depends on what people do.",
                paths=[dict(id=k, label=lab, years=years, median=m, low=[round(v * 0.7, 2) for v in m],
                            high=[round(v * 1.3, 2) for v in m]) for k, (lab, m) in paths.items()],
                provenance=[dict(what="Future scenarios", source="Stylised placeholder", product="not CMIP6 yet",
                                 url="https://www.nccs.nasa.gov/services/data-collections/land-based-products/nex-gddp-cmip6",
                                 retrieved_at="2026-11-14", license="—")])


SHOWCASE = [
    # (файл, місто, змінна, сезон, напрямок твердження, текст, сценарії)
    ("kyiv-summer-heat", "kyiv", "air_temp", "JJA", "increase", "Summers in Kyiv are getting hotter", stylised_heat),
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
        r, _ = build(c, v, s, dr, claim, scenarios=scen() if scen else None)
        (CASES / f"{fname}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1))
        if i == 0:
            (CASES / "mock.json").write_text(json.dumps(r, ensure_ascii=False, indent=1))
        print(f"{fname}: {r['verdict']} ({r['reason']}), {r['sen']['slope_per_decade']:+.3f} {r['variable']['units']}/10 р.")


if __name__ == "__main__":
    main()
