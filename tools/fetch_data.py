#!/usr/bin/env python3
"""Завантаження даних для Earth Verdict: NASA POWER (місячні ряди) + станція NOAA.

Тільки стандартна бібліотека, нічого встановлювати не треба.

Приклади:
  python3 tools/fetch_data.py kyiv                 # одне місто зі списку
  python3 tools/fetch_data.py kyiv lviv odesa      # кілька
  python3 tools/fetch_data.py --all                # усі міста зі списку
  python3 tools/fetch_data.py --lat 50.45 --lon 30.52 --name mycity
  python3 tools/fetch_data.py kyiv --refresh       # ігнорувати кеш
  python3 tools/fetch_data.py --cag                # аномалії температури регіонів світу
  python3 tools/fetch_data.py kyiv --giovanni      # + GPM і GLDAS з Giovanni (токен Earthdata)

Результат: data/<місто>.json. Сирі відповіді API лежать у data/cache/ (повторний запуск
працює без інтернету).
"""
import argparse
import hashlib
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = DATA / "cache"
UA = {"User-Agent": "Mozilla/5.0 (EarthVerdict hackathon fetcher)"}

START, END = 1981, 2025
# °C, °C, °C, мм/добу, см снігу, волога кореневого шару 0–1, сонячна радіація МДж/м²/добу
# (ALLSKY_SFC_SW_DWN порожній до 1984 року: дані CERES/SRB починаються пізніше)
POWER_PARAMS = ["T2M", "T2M_MAX", "T2M_MIN", "PRECTOTCORR", "SNODP", "GWETROOT", "ALLSKY_SFC_SW_DWN"]
NOAA_TYPES = ["TAVG", "TMAX", "PRCP"]

CITIES = {
    "kyiv": ("Київ", 50.45, 30.52),
    "lviv": ("Львів", 49.84, 24.03),
    "odesa": ("Одеса", 46.48, 30.73),
    "kharkiv": ("Харків", 49.99, 36.23),
    "warsaw": ("Варшава", 52.23, 21.01),
}


def get_text(url, params, refresh=False, retries=3, headers=None, ext="txt", validate=None):
    """GET з файловим кешем. Ключ кешу — хеш URL; заголовки (і токен) в ключ і в кеш не потрапляють."""
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    path = CACHE / f"{hashlib.sha1(full.encode()).hexdigest()[:16]}.{ext}"
    if path.exists() and not refresh:
        return path.read_text()
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(full, headers={**UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=300) as r:
                text = r.read().decode()
            if validate:
                validate(text)
            CACHE.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            return text
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500 and e.code != 429:  # помилка запиту чи доступу: повтор не допоможе
                raise RuntimeError(f"{e.code} для {full}: {e.read()[:200]!r}")
            last = e
        except Exception as e:  # мережа, 5xx, битий JSON
            last = e
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"не вдалося отримати {full}: {last}")


def get_json(url, params, refresh=False, retries=3, headers=None):
    return json.loads(get_text(url, params, refresh, retries, headers, "json", validate=json.loads))


def months():
    return [f"{y}-{m:02d}" for y in range(START, END + 1) for m in range(1, 13)]


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(a))


def fetch_power(lat, lon, refresh):
    r = get_json(
        "https://power.larc.nasa.gov/api/temporal/monthly/point",
        dict(parameters=",".join(POWER_PARAMS), community="AG", latitude=lat, longitude=lon,
             start=START, end=END, format="JSON"),
        refresh,
    )
    par = r["properties"]["parameter"]
    series = {}
    for p in POWER_PARAMS:
        # ключі YYYYMM; YYYY13 — річне середнє, його ми не беремо; -999 — пропуск
        series[p] = [
            (None if par[p].get(m.replace("-", ""), -999) <= -900 else round(par[p][m.replace("-", "")], 3))
            for m in months()
        ]
    return {
        "units": {p: r["parameters"][p]["units"] for p in POWER_PARAMS},
        "grid_cell": r["geometry"]["coordinates"][:2],
        "series": series,
    }


def fetch_station(lat, lon, refresh, max_candidates=5):
    """Шукає станції NOAA GSOM у квадраті ±0.7°/±1.0° і бере ту, де найбільше місяців TAVG."""
    bbox = f"{lat + 0.7},{lon - 1.0},{lat - 0.7},{lon + 1.0}"  # N,W,S,E
    found = get_json(
        "https://www.ncei.noaa.gov/access/services/search/v1/data",
        dict(dataset="global-summary-of-the-month", bbox=bbox,
             startDate=f"{START}-01-01", endDate=f"{END}-12-31", limit=20),
        refresh,
    )
    cands = []
    for x in found.get("results", []):
        stn = x["stations"][0]
        lon_s, lat_s = x["boundingPoints"][0]["coordinates"]
        cands.append((haversine_km(lat, lon, lat_s, lon_s), stn["id"], stn["name"], lat_s, lon_s))
    cands.sort()

    best = None
    for dist, sid, name, lat_s, lon_s in cands[:max_candidates]:
        rows = get_json(
            "https://www.ncei.noaa.gov/access/services/data/v1",
            dict(dataset="global-summary-of-the-month", stations=sid,
                 startDate=f"{START}-01-01", endDate=f"{END}-12-31",
                 dataTypes=",".join(NOAA_TYPES), format="json", units="metric"),
            refresh,
        )
        by_month = {row["DATE"]: row for row in rows}  # DATE має вигляд YYYY-MM
        series = {}
        for t in NOAA_TYPES:
            # значення в API — рядки; відсутні місяці залишаються None
            series[t] = [
                (round(float(by_month[m][t]), 2) if m in by_month and by_month[m].get(t) not in (None, "") else None)
                for m in months()
            ]
        covered = sum(v is not None for v in series["TAVG"])
        print(f"    станція {sid} {name} ({dist:.0f} км): TAVG {covered} з {len(months())} місяців")
        if best is None or covered > best["tavg_months"]:
            best = dict(id=sid, name=name, lat=lat_s, lon=lon_s, distance_km=round(dist),
                        tavg_months=covered, tavg_source="gsom", series=series)

    if best and best["tavg_months"] < MIN_COVERAGE * len(months()):
        daily = tavg_from_daily(best["id"], refresh)
        n = sum(v is not None for v in daily)
        print(f"    GSOM покриває мало, TAVG з добових GHCN-Daily: {n} з {len(months())} місяців")
        if n > best["tavg_months"]:
            # Увесь ряд з одного методу, без склеювання з GSOM: у Києві місячне середнє з
            # добових систематично нижче за GSOM на ~0.27 °C, склейка дала б штучну сходинку.
            best["series"]["TAVG"] = daily
            best["tavg_months"] = n
            best["tavg_source"] = f"ghcnd-daily-mean (місяць зараховано, якщо ≥ {MIN_DAYS} днів)"
    return best


MIN_COVERAGE = 0.9  # частка місяців, нижче якої беремо TAVG з добових
MIN_DAYS = 25       # мінімум днів із даними, щоб порахувати місячне середнє


def tavg_from_daily(station_id, refresh):
    """Місячне середнє TAVG з добових GHCN-Daily, по одному запиту на рік (кешується)."""
    days = {}
    for y in range(START, END + 1):
        rows = get_json(
            "https://www.ncei.noaa.gov/access/services/data/v1",
            dict(dataset="daily-summaries", stations=station_id,
                 startDate=f"{y}-01-01", endDate=f"{y}-12-31",
                 dataTypes="TAVG", format="json", units="metric"),
            refresh,
        )
        for r in rows:
            v = r.get("TAVG")
            if v not in (None, ""):
                days.setdefault(r["DATE"][:7], []).append(float(v))
    return [
        (round(sum(days[m]) / len(days[m]), 2) if len(days.get(m, [])) >= MIN_DAYS else None)
        for m in months()
    ]


GIOVANNI = "https://api.giovanni.earthdata.nasa.gov"
TOKEN_FILE = Path.home() / ".config" / "earthdata" / "token"
# ключ → (ID змінної Giovanni, множник до наших одиниць, наші одиниці, опис)
GIOVANNI_VARS = {
    "precip_gpm": ("GPM_3IMERGM_07_precipitation", 24, "mm/day", "Опади GPM IMERG (супутники + опадоміри), 0.1°"),
    "evap_gldas": ("GLDAS_NOAH025_M_2_1_Evap_tavg", 86400, "mm/day", "Випаровування з суші, модель GLDAS Noah 2.1, 0.25°"),
}


def earthdata_token():
    import os
    tok = os.environ.get("EARTHDATA_TOKEN") or (TOKEN_FILE.read_text().strip() if TOKEN_FILE.exists() else "")
    if not tok:
        sys.exit(f"немає токена Earthdata: задай EARTHDATA_TOKEN або поклади його у {TOKEN_FILE}")
    return tok


def fetch_giovanni(lat, lon, refresh):
    """Місячні ряди Giovanni Time Series API для точки. Квота витрачається лише без кешу."""
    auth = {"Authorization": "Bearer " + earthdata_token()}
    out = {}
    for key, (var, factor, units, label) in GIOVANNI_VARS.items():
        csv = get_text(
            f"{GIOVANNI}/timeseries",
            {"data": var, "location": f"[{lat},{lon}]", "time": f"{START}-01-01T00:00:00/{END}-12-31T23:59:59"},
            refresh, headers=auth, ext="csv",
            validate=lambda t: t.index("Timestamp (UTC),Data"),
        )
        head, body = csv.split("Timestamp (UTC),Data", 1)
        meta = dict(line.split(",", 1) for line in head.strip().splitlines() if "," in line)
        undef = float(meta.get("undef", "-9999.9"))
        values = {}
        for line in body.strip().splitlines():
            ts, v = line.split(",", 1)
            if v.strip() not in ("", "undef") and float(v) != undef:
                values[ts[:7]] = round(float(v) * factor, 4)
        series = [values.get(m) for m in months()]
        out[key] = {
            "variable": var, "label": label, "units": units,
            "source_units": meta.get("unit"), "doi": meta.get("doi"),
            "cell": [float(meta.get("lat", lat)), float(meta.get("lon", lon))],
            "series": series,
        }
        n = sum(v is not None for v in series)
        print(f"    Giovanni {var}: {n} місяців ({meta.get('begin_time', '?')[:7]} – {meta.get('end_time', '?')[:7]})")
    return out


CAG_REGIONS = ["globe", "europe", "asia", "africa", "northAmerica", "southAmerica", "oceania", "arctic"]
CAG_SEASONS = {"year": (12, 12), "jja": (3, 8), "djf": (3, 2)}  # (кількість місяців, останній місяць)


def fetch_cag(refresh):
    """NOAA Climate at a Glance: аномалії температури суша+океан відносно 1901–2000."""
    base = "https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/global/time-series"
    out = {"source": "NOAA NCEI Climate at a Glance", "units": "°C", "base_period": "1901-2000", "regions": {}}
    for region in CAG_REGIONS:
        out["regions"][region] = {}
        for season, (span, month) in CAG_SEASONS.items():
            try:
                d = get_json(f"{base}/{region}/land_ocean/{span}/{month}/1850-{END + 1}/data.json", {}, refresh)
            except RuntimeError as e:
                print(f"  CAG {region}/{season}: {e}", file=sys.stderr)
                continue
            years = sorted(d["data"], key=int)
            out["regions"][region][season] = {
                "years": [int(y) for y in years],
                "anomaly": [d["data"][y].get("departure") if isinstance(d["data"][y], dict) else d["data"][y]
                            for y in years],
            }
            last = years[-1]
            print(f"  CAG {region:13} {season}: {years[0]}–{last}, останнє {out['regions'][region][season]['anomaly'][-1]}")
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "cag.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    print(f"  збережено data/cag.json")


def run(key, name, lat, lon, refresh, giovanni=False):
    print(f"{name} ({lat}, {lon})")
    print("  NASA POWER ...")
    power = fetch_power(lat, lon, refresh)
    print("  NOAA ...")
    station = fetch_station(lat, lon, refresh)
    out = {
        "name": name, "lat": lat, "lon": lon,
        "months_start": f"{START}-01", "months_end": f"{END}-12",
        "retrieved": time.strftime("%Y-%m-%d"),
        "sources": {
            "power": "NASA POWER monthly point (MERRA-2/CERES), https://power.larc.nasa.gov",
            "station": "NOAA NCEI Global Summary of the Month / GHCN-Daily",
        },
        "power": power,
        "station": station,
    }
    if giovanni:
        print("  Giovanni ...")
        out["giovanni"] = fetch_giovanni(lat, lon, refresh)
        out["sources"]["giovanni"] = "NASA GES DISC Giovanni Time Series API"
    DATA.mkdir(parents=True, exist_ok=True)
    path = DATA / f"{key}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    print(f"  збережено {path.relative_to(ROOT)} ({path.stat().st_size // 1024} КБ)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cities", nargs="*", help=f"ключі міст: {', '.join(CITIES)}")
    ap.add_argument("--all", action="store_true", help="усі міста зі списку")
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float)
    ap.add_argument("--name", default="custom", help="назва для власних координат")
    ap.add_argument("--refresh", action="store_true", help="ігнорувати кеш")
    ap.add_argument("--cag", action="store_true", help="аномалії Climate at a Glance для регіонів світу")
    ap.add_argument("--giovanni", action="store_true",
                    help=f"додати ряди Giovanni (потрібен токен у EARTHDATA_TOKEN або {TOKEN_FILE})")
    a = ap.parse_args()

    if a.cag:
        fetch_cag(a.refresh)
        if not (a.cities or a.all or a.lat is not None):
            return

    jobs = []
    if a.lat is not None and a.lon is not None:
        jobs.append((a.name, a.name, a.lat, a.lon))
    keys = list(CITIES) if a.all else a.cities
    for k in keys:
        if k not in CITIES:
            sys.exit(f"невідоме місто '{k}'. Доступні: {', '.join(CITIES)}")
        n, la, lo = CITIES[k]
        jobs.append((k, n, la, lo))
    if not jobs:
        ap.error("вкажи місто, --all або --lat/--lon")

    for key, name, lat, lon in jobs:
        try:
            run(key, name, lat, lon, a.refresh, a.giovanni)
        except Exception as e:
            print(f"  ПОМИЛКА для {name}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
