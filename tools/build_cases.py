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
from app.models import CheckResult  # noqa: E402
from app.stats import build_extrapolation, months_for_season, seasonal_series  # noqa: E402
from app.verdict import ALPHA, evaluate_verdict, sig3  # noqa: E402

DATA = ROOT / "data"
CASES = DATA / "cases"

# variable_id → як брати й агрегувати; тексти англійською (мова інтерфейсу за ТЗ)
VARIABLES = {
    "air_temp": dict(power="T2M", station="TAVG", agg="mean", units="°C", dec=2,
                     label="Air temperature",
                     definition="How warm the air is about 2 m above the ground.",
                     caveat="Reanalysis: a weather model steered by observations, not a single thermometer.",
                     product="T2M (MERRA-2)"),
    "precip": dict(power="PRECTOTCORR", station="PRCP", agg="sum", units="mm", dec=1,
                   label="Precipitation",
                   definition="How much rain and melted snow falls in total.",
                   caveat="Bias-corrected reanalysis; local showers can be missed.",
                   product="PRECTOTCORR (MERRA-2, bias-corrected)"),
    "snow_depth": dict(power="SNODP", station=None, agg="mean", units="cm", dec=1,
                       label="Snow depth",
                       definition="How thick the snow layer on the ground is, on average.",
                       caveat="Modelled snow, not measured on site.",
                       product="SNODP (MERRA-2)"),
}

SEASON_LABEL = {"year": "the whole year", "DJF": "winter (Dec–Feb)", "MAM": "spring (Mar–May)",
                "JJA": "summer (Jun–Aug)", "SON": "autumn (Sep–Nov)"}


# ---------- дані ----------

def load_city(key):
    return json.loads((DATA / f"{key}.json").read_text())


# ---------- одна справа ----------

def build(city_key, variable_id, season, direction, claim, start=1981, end=2025, scenarios=None):
    city = load_city(city_key)
    var = VARIABLES[variable_id]
    if season == "DJF" and start == 1981:
        start = 1982  # для зими 1981 немає грудня 1980
    data_start_y, data_start_m = map(int, city.get("months_start", "1981-01").split("-"))
    per_day = var["agg"] == "sum"
    years, vals = seasonal_series(
        city["power"]["series"][var["power"]],
        season,
        var["agg"],
        start,
        end,
        per_day=per_day,
        data_start_year=data_start_y,
        data_start_month=data_start_m,
    )

    st = city.get("station")
    wy, wv = None, None
    if var["station"] and st and var["station"] in st.get("series", {}):
        wy, wv = seasonal_series(
            st["series"][var["station"]],
            season,
            var["agg"],
            start,
            end,
            per_day=False,
            data_start_year=data_start_y,
            data_start_month=data_start_m,
        )

    ev = evaluate_verdict(
        years,
        vals,
        direction=direction,
        start_year=start,
        end_year=end,
        witness_years=wy,
        witness_values=wv,
    )
    main = ev.main
    rob = [
        dict(
            start_year=w.start_year,
            end_year=w.end_year,
            p=sig3(w.p),
            slope_per_decade=round(w.slope_per_decade, 4),
            significant=w.significant,
        )
        for w in ev.robustness.windows
    ]
    n_sig = ev.robustness.significant

    witness = None
    w_agree = ev.witness_agreement
    if ev.witness_trend and wy is not None and wv is not None and st is not None:
        wt = ev.witness_trend
        witness = dict(
            station=dict(id=st["id"], name=st["name"].title(), lat=st["lat"], lon=st["lon"], distance_km=st["distance_km"]),
            series=[dict(year=y, value=None if v is None else round(v, var["dec"])) for y, v in zip(wy, wv)],
            coverage=round(ev.witness_coverage or 0.0, 3),
            method_note=("Monthly means computed from daily GHCN-Daily records (≥25 days per month)"
                         if variable_id == "air_temp" and st.get("tavg_source", "").startswith("ghcnd") else None),
            sen=dict(
                slope_per_decade=round(wt.sen.slope_per_decade, 4),
                ci_low=round(wt.sen.ci_low_per_year * 10, 4),
                ci_high=round(wt.sen.ci_high_per_year * 10, 4),
            ),
            mk=dict(p=sig3(wt.mk.p)),
            agreement=w_agree,
        )

    verdict, reason, wait = ev.verdict, ev.reason, ev.years_to_wait
    sig = main.mk.p < ALPHA

    u, d = var["units"], var["dec"]
    dec = lambda v: f"{v * 10:+.{d}f} {u} per 10 years"
    season_months = months_for_season(season)
    season_step_val = SEASON_LABEL[season] if isinstance(season, str) else calendar.month_name[season_months[0]]
    steps = [
        dict(id="raw", title="Monthly data", value=f"{(end - start + 1) * 12} months",
             detail=f"Monthly {var['label'].lower()} for {city['name']} from NASA POWER, {start}–{end}."),
        dict(id="season", title="Pick the season", value=season_step_val,
             detail=f"Only the months the claim is about are kept ({', '.join(calendar.month_abbr[m] for m in season_months)})."),
        dict(id="yearly", title="One value per year", value=f"{main.n} years",
             detail=f"The months of each year are {'added up' if var['agg'] == 'sum' else 'averaged'} into one number."),
        dict(id="trend", title="Overall direction", value=dec(main.sen.slope_per_year),
             detail="The typical change over time, robust to single extreme years (Sen's slope)."),
        dict(id="random_check", title="Could it be chance?", value=f"p = {main.mk.p:.3f}" if main.mk.p >= 0.001 else "p < 0.001",
             detail=("Very unlikely to appear by chance if nothing were changing." if sig
                     else "A slope like this easily appears by chance when weather simply varies.")),
        dict(id="robustness", title="Does the choice of years matter?", value=f"{n_sig} of {len(rob)} periods agree",
             detail="We repeat the check with the start and end shifted by a few years."),
        dict(id="witness", title="Ground station check",
             value={"agree": "Station agrees", "disagree": "Station disagrees", "one_source": "Station sees no clear change",
                    "no_station": "No station"}[w_agree],
             detail=(f"{witness['station']['name']} weather station, {witness['station']['distance_km']} km away."
                     if witness else "No nearby station with long enough records for this variable.")),
        dict(id="verdict", title="Verdict", value={"confirmed": "Confirmed", "refuted": "Refuted", "not_proven": "Not proven"}[verdict],
             detail={"significant_trend": "A clear, robust trend in the direction of the claim.",
                     "opposite_trend": "A clear, robust trend in the opposite direction.",
                     "not_significant": "Year-to-year swings are larger than the change so far.",
                     "not_robust": "The result depends on which years you pick.",
                     "sources_disagree": "Satellite-model data and the station point in different directions.",
                     "short_series": "Too few years to judge."}[reason]),
    ]

    lat, lon = city["lat"], city["lon"]
    prov = [dict(what=var["label"], source="NASA POWER", product=var["product"],
                 url=f"https://power.larc.nasa.gov/api/temporal/monthly/point?parameters={var['power']}&community=AG"
                     f"&latitude={lat}&longitude={lon}&start={start if season != 'DJF' else start - 1}&end={end}&format=JSON",
                 retrieved_at=city["retrieved"], license="Public domain (NASA)")]
    if witness:
        prov.append(dict(what=f"{var['label']} at weather station", source="NOAA NCEI",
                         product="GHCN-Daily → monthly" if witness["method_note"] else "Global Summary of the Month",
                         url=f"https://www.ncei.noaa.gov/access/services/data/v1?dataset="
                             f"{'daily-summaries' if witness['method_note'] else 'global-summary-of-the-month'}"
                             f"&stations={witness['station']['id']}&dataTypes={var['station']}&units=metric&format=json",
                         retrieved_at=city["retrieved"], license="Public domain (NOAA)"))

    det = ev.detection
    detection = dict(
        residual_sd=round(det.residual_sd, 4),
        phi=round(det.phi, 4),
        slope_per_year=round(det.slope_per_year, 5),
        n_years=det.n_years,
        multipliers=det.multipliers,
        years_needed=det.years_needed,
    )

    extrapolation = build_extrapolation(
        slope_per_year=main.sen.slope_per_year,
        ci_low_per_year=main.sen.ci_low_per_year,
        ci_high_per_year=main.sen.ci_high_per_year,
        intercept_at_start=main.sen.intercept_at_start,
        start_year=start,
        end_year=end,
        decimals=d,
    )

    scen = None
    if scenarios:
        i0, i1 = years.index(1995), years.index(2014) + 1
        base = [v for v in vals[i0:i1] if v is not None]
        scen = dict(**scenarios, baseline_value=round(sum(base) / len(base), d))
        prov.append(dict(what="Future scenarios", source="Stylised placeholder", product="not CMIP6 yet",
                         url="https://www.nccs.nasa.gov/services/data-collections/land-based-products/nex-gddp-cmip6",
                         retrieved_at=city["retrieved"], license="—"))

    result = dict(
        case=dict(claim_text=claim, variable_id=variable_id,
                  place=dict(place_id=f"city:{city_key}", name=city["name"], lat=lat, lon=lon),
                  season=season, start_year=start, end_year=end, claim_direction=direction),
        variable=dict(id=variable_id, label=var["label"], units=u, definition=var["definition"], caveat=var["caveat"]),
        series=[dict(year=y, value=None if v is None else round(v, d)) for y, v in zip(years, vals)],
        sen=dict(
            slope_per_year=round(main.sen.slope_per_year, 5),
            slope_per_decade=round(main.sen.slope_per_decade, 4),
            ci_low=round(main.sen.ci_low_per_year * 10, 4),
            ci_high=round(main.sen.ci_high_per_year * 10, 4),
            intercept=round(main.sen.intercept_at_start, 3),
        ),
        mk=dict(p=sig3(main.mk.p), tau=round(main.mk.tau, 4), z=round(main.mk.z, 3), correction=main.mk.correction),
        ols=dict(
            slope_per_year=round(main.ols.slope_per_year, 5),
            p=sig3(main.ols.p),
            r2=round(main.ols.r2, 4),
            n_eff=round(main.ols.n_eff, 1),
        ),
        robustness=rob,
        robustness_summary=dict(significant=n_sig, total=len(rob)),
        witness=witness, verdict=verdict, reason=reason, years_to_wait=wait,
        steps=steps, detection=detection, extrapolation=extrapolation, scenarios=scen, provenance=prov,
        meta=dict(stub=True, stats_engine="backend.app.stats v2",
                  generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
    )
    return CheckResult.model_validate(result).model_dump(mode="json"), ev


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
                            high=[round(v * 1.3, 2) for v in m]) for k, (lab, m) in paths.items()])


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
