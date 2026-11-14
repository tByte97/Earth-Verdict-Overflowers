#!/usr/bin/env python3
"""Збирає показові справи (CheckResult) з даних, викачаних tools/fetch_data.py.

Статистика тут ТИМЧАСОВА: готові бібліотеки (pymannkendall, scipy), щоб у заглушці для
фронтенду були справжні числа, узгоджені з рядом. Власний модуль backend/app/stats/
(задача #12) її замінить.

Запуск (з кореня репозиторію):
  backend/.venv/bin/python tools/build_cases.py --explore   # таблиця кандидатів
  backend/.venv/bin/python tools/build_cases.py             # data/cases/*.json + mock.json
"""
import argparse
import calendar
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pymannkendall as pmk
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from app.models import CheckResult  # noqa: E402

DATA = ROOT / "data"
CASES = DATA / "cases"
ALPHA = 0.05
MIN_YEARS = 15
ROBUST_NEED = 4  # значущих вікон із 5

SEASON_MONTHS = {"year": list(range(1, 13)), "DJF": [12, 1, 2], "MAM": [3, 4, 5], "JJA": [6, 7, 8], "SON": [9, 10, 11]}

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


def monthly_lookup(arr, start="1981-01"):
    y0, m0 = map(int, start.split("-"))
    def get(y, m):
        i = (y - y0) * 12 + (m - m0)
        return arr[i] if 0 <= i < len(arr) else None
    return get


def seasonal(arr, season, agg, y_from, y_to, per_day=False):
    """Одне значення на рік. DJF року Y = грудень Y-1 + січень, лютий Y. Рік з пропуском → None.
    per_day=True: значення в мм/добу, для суми множимо на кількість днів місяця."""
    get = monthly_lookup(arr)
    out = []
    for y in range(y_from, y_to + 1):
        vals = []
        for m in SEASON_MONTHS[season]:
            yy = y - 1 if (season == "DJF" and m == 12) else y
            v = get(yy, m)
            if v is None:
                vals = None
                break
            if agg == "sum" and per_day:
                v *= calendar.monthrange(yy, m)[1]
            vals.append(v)
        out.append(None if vals is None else (sum(vals) if agg == "sum" else sum(vals) / len(vals)))
    return list(range(y_from, y_to + 1)), out


# ---------- тимчасова статистика ----------

def sig3(p):
    """p-значення до трьох значущих цифр: 1.23e-07, а не 0.0."""
    return float(f"{p:.3g}")


def lag1(res):
    r = np.asarray(res) - np.mean(res)
    return float(np.sum(r[1:] * r[:-1]) / np.sum(r * r)) if np.sum(r * r) > 0 else 0.0


def trend(years, values):
    x = np.array([y for y, v in zip(years, values) if v is not None], float)
    y = np.array([v for v in values if v is not None], float)
    n = len(y)
    if n < MIN_YEARS:
        return None
    ts = stats.theilslopes(y, x, alpha=0.95)
    with np.errstate(invalid="ignore"):
        mk = pmk.hamed_rao_modification_test(y)
    if not math.isfinite(mk.p):
        # TODO(#12): Hamed–Rao іноді дає від'ємну дисперсію (Харків, опади JJA) → NaN.
        # Тимчасово: звичайний тест; у власному модулі — обмежити поправку знизу.
        mk = pmk.original_test(y)
    lr = stats.linregress(x, y)
    res = y - (lr.intercept + lr.slope * x)
    r1 = lag1(res)
    n_eff = n * (1 - r1) / (1 + r1) if r1 > 0 else float(n)
    t = lr.slope / lr.stderr * math.sqrt(max(n_eff - 2, 1) / (n - 2)) if lr.stderr > 0 else 0.0
    p_ols = float(2 * stats.t.sf(abs(t), max(n_eff - 2, 1)))
    # Weatherhead et al. 1998: скільки років треба, щоб такий нахил став помітним
    phi = min(max(r1, 0.0), 0.9)
    sd = float(np.std(res, ddof=1))
    n_star = (3.3 * sd / abs(ts.slope) * math.sqrt((1 + phi) / (1 - phi))) ** (2 / 3) if ts.slope else math.inf
    return dict(n=n, x0=float(x[0]), slope=float(ts.slope), lo=float(ts.low_slope), hi=float(ts.high_slope),
                intercept_at_start=float(ts.intercept + ts.slope * x[0]),
                mk_p=float(mk.p), tau=float(mk.Tau), z=float(mk.z),
                ols_slope=float(lr.slope), ols_p=p_ols, r2=float(lr.rvalue ** 2), n_eff=float(n_eff),
                r1=r1, sd=sd, n_star=n_star)


def windows(start, end):
    cands = [(start, end), (start + 3, end), (start + 6, end), (start, end - 3), (start + 3, end - 3)]
    return [(a, b) for a, b in cands if b - a + 1 >= MIN_YEARS]


def sign_ok(direction, slope):
    return {"increase": slope > 0, "decrease": slope < 0, "change": slope != 0}[direction]


# ---------- одна справа ----------

def build(city_key, variable_id, season, direction, claim, start=1981, end=2025, scenarios=None):
    city = load_city(city_key)
    var = VARIABLES[variable_id]
    if season == "DJF" and start == 1981:
        start = 1982  # для зими 1981 немає грудня 1980
    per_day = var["agg"] == "sum"
    years, vals = seasonal(city["power"]["series"][var["power"]], season, var["agg"], start, end, per_day)
    main = trend(years, vals)

    rob = []
    for a, b in windows(start, end):
        i0, i1 = years.index(a), years.index(b) + 1
        t = trend(years[i0:i1], vals[i0:i1])
        rob.append(dict(start_year=a, end_year=b, p=sig3(t["mk_p"]), slope_per_decade=round(t["slope"] * 10, 4),
                        significant=bool(t["mk_p"] < ALPHA and np.sign(t["slope"]) == np.sign(main["slope"]))))
    n_sig = sum(w["significant"] for w in rob)

    witness, w_agree = None, "no_station"
    st = city.get("station")
    if var["station"] and st:
        wy, wv = seasonal(st["series"][var["station"]], season, var["agg"], start, end, per_day=False)
        cov = sum(v is not None for v in wv) / len(wv)
        wt = trend(wy, wv) if cov >= 0.6 else None
        if wt:
            same = np.sign(wt["slope"]) == np.sign(main["slope"])
            w_agree = "agree" if (wt["mk_p"] < ALPHA and same) else "disagree" if (wt["mk_p"] < ALPHA and not same) else "one_source"
            witness = dict(
                station=dict(id=st["id"], name=st["name"].title(), lat=st["lat"], lon=st["lon"], distance_km=st["distance_km"]),
                series=[dict(year=y, value=None if v is None else round(v, var["dec"])) for y, v in zip(wy, wv)],
                coverage=round(cov, 3),
                method_note=("Monthly means computed from daily GHCN-Daily records (≥25 days per month)"
                             if variable_id == "air_temp" and st.get("tavg_source", "").startswith("ghcnd") else None),
                sen=dict(slope_per_decade=round(wt["slope"] * 10, 4), ci_low=round(wt["lo"] * 10, 4), ci_high=round(wt["hi"] * 10, 4)),
                mk=dict(p=sig3(wt["mk_p"])),
                agreement=w_agree,
            )

    # ---------- вердикт ----------
    sig = main["mk_p"] < ALPHA
    if main["n"] < MIN_YEARS:
        verdict, reason = "not_proven", "short_series"
    elif not sig:
        verdict, reason = "not_proven", "not_significant"
    elif n_sig < ROBUST_NEED:
        verdict, reason = "not_proven", "not_robust"
    elif w_agree == "disagree":
        verdict, reason = "not_proven", "sources_disagree"
    elif sign_ok(direction, main["slope"]):
        verdict, reason = "confirmed", "significant_trend"
    else:
        verdict, reason = "refuted", "opposite_trend"
    wait = None
    if verdict == "not_proven" and math.isfinite(main["n_star"]) and main["n_star"] > main["n"]:
        # TODO(#12): коли n* ≤ n, а тест не значущий, формула суперечить тесту — тоді не показуємо.
        wait = math.ceil(main["n_star"] - main["n"])

    u, d = var["units"], var["dec"]
    dec = lambda v: f"{v * 10:+.{d}f} {u} per 10 years"
    steps = [
        dict(id="raw", title="Monthly data", value=f"{(end - start + 1) * 12} months",
             detail=f"Monthly {var['label'].lower()} for {city['name']} from NASA POWER, {start}–{end}."),
        dict(id="season", title="Pick the season", value=SEASON_LABEL[season],
             detail=f"Only the months the claim is about are kept ({', '.join(calendar.month_abbr[m] for m in SEASON_MONTHS[season])})."),
        dict(id="yearly", title="One value per year", value=f"{main['n']} years",
             detail=f"The months of each year are {'added up' if var['agg'] == 'sum' else 'averaged'} into one number."),
        dict(id="trend", title="Overall direction", value=dec(main["slope"]),
             detail="The typical change over time, robust to single extreme years (Sen's slope)."),
        dict(id="random_check", title="Could it be chance?", value=f"p = {main['mk_p']:.3f}" if main["mk_p"] >= 0.001 else "p < 0.001",
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
        sen=dict(slope_per_year=round(main["slope"], 5), slope_per_decade=round(main["slope"] * 10, 4),
                 ci_low=round(main["lo"] * 10, 4), ci_high=round(main["hi"] * 10, 4),
                 intercept=round(main["intercept_at_start"], 3)),
        mk=dict(p=sig3(main["mk_p"]), tau=round(main["tau"], 4), z=round(main["z"], 3), correction="hamed_rao"),
        ols=dict(slope_per_year=round(main["ols_slope"], 5), p=sig3(main["ols_p"]), r2=round(main["r2"], 4),
                 n_eff=round(main["n_eff"], 1)),
        robustness=rob,
        robustness_summary=dict(significant=n_sig, total=len(rob)),
        witness=witness, verdict=verdict, reason=reason, years_to_wait=wait,
        steps=steps, scenarios=scen, provenance=prov,
        meta=dict(stub=True, stats_engine="provisional: pymannkendall 1.4.3 (Hamed–Rao) + scipy theilslopes/linregress",
                  generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
    )
    return CheckResult.model_validate(result).model_dump(mode="json"), main


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
