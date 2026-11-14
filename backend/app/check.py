"""Check pipeline: CaseSpec -> CheckResult.

`assemble_result` is pure (monthly series in, CheckResult out) and is shared by the API and by
tools/build_cases.py, so showcase cases and live checks are computed by the same code.
`run_check` fetches the data through app.sources and calls it.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Sequence

from .catalog import VariableDef, get_variable
from .models import CaseSpec, CheckResult
from .scenarios import add_observed_context, nearby_scenarios
from .stats import build_extrapolation, months_for_season, seasonal_series
from .stats.witness import compare_rates
from .verdict import ALPHA, MIN_YEARS, evaluate_verdict, sig3

STATS_ENGINE = "backend.app.stats v2"

SEASON_LABEL = {"year": "the whole year", "DJF": "winter (Dec–Feb)", "MAM": "spring (Mar–May)",
                "JJA": "summer (Jun–Aug)", "SON": "autumn (Sep–Nov)"}

# NOAA keeps old Russian transliterations; show current Ukrainian ones.
STATION_RENAMES = {"Kiev": "Kyiv", "Kharkov": "Kharkiv", "Odessa": "Odesa", "Lvov": "Lviv"}

METHOD_NOTES = {
    "gsom": None,
    "ghcnd-daily-mean": "Monthly means computed from daily GHCN-Daily records (≥25 days per month)",
    "ghcnd-daily-sum": "Monthly totals computed from complete months of daily GHCN-Daily records",
}

SOURCE_LABEL = {"power": "NASA POWER", "giovanni": "NASA Giovanni", "cag": "NOAA Climate at a Glance"}

# Regions for global_temp: place_id "region:<key>". A normal place means the whole planet.
REGIONS = {"globe": ("The whole planet", 0.0, 0.0), "europe": ("Europe", 50.0, 15.0),
           "asia": ("Asia", 45.0, 90.0), "africa": ("Africa", 5.0, 20.0),
           "northamerica": ("North America", 45.0, -100.0), "southamerica": ("South America", -15.0, -60.0),
           "oceania": ("Oceania", -25.0, 135.0), "arctic": ("The Arctic", 80.0, 0.0)}


def region_key(place) -> str:
    pid = place.place_id.lower()
    key = pid.split(":", 1)[1] if pid.startswith("region:") else "globe"
    return key if key in REGIONS else "globe"


def region_name(place) -> str:
    return REGIONS[region_key(place)][0]


class CheckError(Exception):
    """Maps to ErrorResponse codes: unknown_variable, short_series, bad_request, source_unavailable."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class MainSeries:
    monthly: Sequence[Optional[float]]
    start: str                      # "YYYY-MM" of monthly[0]
    url: str
    retrieved_at: str
    # Sources that already give one value per year and season (Climate at a Glance) set this
    # instead of `monthly`: {year: value}.
    yearly: Optional[dict[int, Optional[float]]] = None


@dataclass(frozen=True)
class StationInput:
    id: str
    name: str
    lat: float
    lon: float
    distance_km: float
    monthly: Sequence[Optional[float]]
    start: str
    method: str                     # gsom | ghcnd-daily-mean | ghcnd-daily-sum
    url: str
    retrieved_at: str


def station_name(raw: str) -> str:
    """'KIEV, UP' -> 'Kyiv': no country code, current transliteration."""
    base = raw.split(",")[0].strip().title()
    return STATION_RENAMES.get(base, base)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ym(s: str) -> tuple[int, int]:
    y, m = s.split("-")[:2]
    return int(y), int(m)


def effective_start(spec_start: int, season, var: VariableDef) -> int:
    """DJF of year Y needs December of Y-1; without it the first winter is dropped."""
    if season == "DJF" and spec_start <= var.first_year:
        return var.first_year + 1
    return spec_start


def validate_spec(spec: CaseSpec) -> VariableDef:
    var = get_variable(spec.variable_id)
    if var is None:
        raise CheckError("unknown_variable", f"Unknown variable '{spec.variable_id}'.")
    if isinstance(spec.season, int) and not 1 <= spec.season <= 12:
        raise CheckError("bad_request", "Month must be between 1 and 12.")
    if spec.start_year > spec.end_year:
        raise CheckError("bad_request", "Start year must not be after end year.")
    if spec.start_year < var.first_year or spec.end_year > var.last_year:
        raise CheckError("bad_request",
                         f"{var.label} is available for {var.first_year}–{var.last_year}.")
    start = effective_start(spec.start_year, spec.season, var)
    if spec.end_year - start + 1 < MIN_YEARS:
        raise CheckError("short_series", f"At least {MIN_YEARS} years are needed to judge a trend.")
    return var


def _witness_detail(witness: Optional[dict], units: str, dec: int) -> str:
    if not witness:
        return "No nearby station with long enough records for this variable."
    where = f"{witness['station']['name']} weather station, {witness['station']['distance_km']} km away."
    r = witness.get("rates")
    if not r:
        return where
    if r["consistent"]:
        return f"{where} It changes at about the same pace as the satellite-model data."
    faster = r["difference_per_decade"] > 0
    return (f"{where} It changes {'faster' if faster else 'slower'} "
            f"({r['witness_slope_per_decade']:+.{dec}f} vs {r['main_slope_per_decade']:+.{dec}f} {units} per 10 years)"
            + (", which is typical for growing cities." if faster and units == "°C" else "."))


def assemble_result(
    spec: CaseSpec,
    var: VariableDef,
    main_series: MainSeries,
    station: Optional[StationInput] = None,
    *,
    scenarios: Optional[dict] = None,
    stub: bool = False,
) -> CheckResult:
    season = spec.season
    start = effective_start(spec.start_year, season, var)
    end = spec.end_year
    d, u = var.decimals, var.units

    if main_series.yearly is not None:
        years = list(range(start, end + 1))
        vals = [main_series.yearly.get(y) for y in years]
    else:
        y0, m0 = _ym(main_series.start)
        years, vals = seasonal_series(main_series.monthly, season, var.agg, start, end,
                                      per_day=var.per_day, data_start_year=y0, data_start_month=m0)

    wy = wv = None
    if station is not None:
        sy, sm = _ym(station.start)
        # Station monthly values are already monthly totals/means: never per-day.
        wy, wv = seasonal_series(station.monthly, season, var.agg, start, end,
                                 per_day=False, data_start_year=sy, data_start_month=sm)

    ev = evaluate_verdict(years, vals, direction=spec.claim_direction, start_year=start, end_year=end,
                          witness_years=wy, witness_values=wv)
    main = ev.main

    rob = [dict(start_year=w.start_year, end_year=w.end_year, p=sig3(w.p),
                slope_per_decade=round(w.slope_per_decade, 4), significant=w.significant)
           for w in ev.robustness.windows]
    n_sig = ev.robustness.significant

    witness = None
    if ev.witness_trend and station is not None and wy is not None and wv is not None:
        wt = ev.witness_trend
        witness = dict(
            station=dict(id=station.id, name=station_name(station.name), lat=station.lat, lon=station.lon,
                         distance_km=station.distance_km),
            series=[dict(year=y, value=None if v is None else round(v, d)) for y, v in zip(wy, wv)],
            coverage=round(ev.witness_coverage or 0.0, 3),
            method_note=METHOD_NOTES.get(station.method),
            sen=dict(slope_per_decade=round(wt.sen.slope_per_decade, 4),
                     ci_low=round(wt.sen.ci_low_per_year * 10, 4),
                     ci_high=round(wt.sen.ci_high_per_year * 10, 4)),
            mk=dict(p=sig3(wt.mk.p)),
            agreement=ev.witness_agreement,
        )
        rc = compare_rates(years, vals, wy, wv)
        if rc is not None:
            witness["rates"] = dict(
                common_years=rc.common_years,
                main_slope_per_decade=round(rc.main_slope_per_decade, 4),
                witness_slope_per_decade=round(rc.witness_slope_per_decade, 4),
                difference_per_decade=round(rc.difference_per_decade, 4),
                ci_low=round(rc.ci_low, 4), ci_high=round(rc.ci_high, 4),
                p=sig3(rc.p), consistent=rc.consistent,
            )
    w_agree = ev.witness_agreement if witness else "no_station"

    sig = main.mk.p < ALPHA
    per_decade = lambda v: f"{v * 10:+.{d}f} {u} per 10 years"  # noqa: E731
    season_months = months_for_season(season)
    season_value = SEASON_LABEL[season] if isinstance(season, str) else calendar.month_name[season_months[0]]
    src = SOURCE_LABEL[var.source_kind]
    if main_series.yearly is not None:
        raw_step = dict(id="raw", title="Yearly data", value=f"{end - start + 1} years",
                        detail=f"{var.label} for {region_name(spec.place)} from {src}, {start}–{end}, "
                               f"as the difference from the 1901–2000 average.")
    else:
        raw_step = dict(id="raw", title="Monthly data", value=f"{(end - start + 1) * 12} months",
                        detail=f"Monthly {var.label.lower()} for {spec.place.name} from {src}, {start}–{end}.")
    steps = [
        raw_step,
        dict(id="season", title="Pick the season", value=season_value,
             detail=f"Only the months the claim is about are kept "
                    f"({', '.join(calendar.month_abbr[m] for m in season_months)})."),
        dict(id="yearly", title="One value per year", value=f"{main.n} years",
             detail=f"The months of each year are {'added up' if var.agg == 'sum' else 'averaged'} into one number."),
        dict(id="trend", title="Overall direction", value=per_decade(main.sen.slope_per_year),
             detail="The typical change over time, robust to single extreme years (Sen's slope)."),
        dict(id="random_check", title="Could it be chance?",
             value=f"p = {main.mk.p:.3f}" if main.mk.p >= 0.001 else "p < 0.001",
             detail=("Very unlikely to appear by chance if nothing were changing." if sig
                     else "A slope like this easily appears by chance when weather simply varies.")),
        dict(id="robustness", title="Does the choice of years matter?", value=f"{n_sig} of {len(rob)} periods agree",
             detail="We repeat the check with the start and end shifted by a few years."),
        dict(id="witness", title="Ground station check",
             value={"agree": "Station agrees", "disagree": "Station disagrees",
                    "one_source": "Station sees no clear change", "no_station": "No station"}[w_agree],
             detail=_witness_detail(witness, u, d)),
        dict(id="verdict", title="Verdict",
             value={"confirmed": "Confirmed", "refuted": "Refuted", "not_proven": "Not proven"}[ev.verdict],
             detail={"significant_trend": "A clear, robust trend in the direction of the claim.",
                     "opposite_trend": "A clear, robust trend in the opposite direction.",
                     "not_significant": "Year-to-year swings are larger than the change so far.",
                     "not_robust": "The result depends on which years you pick.",
                     "sources_disagree": "Satellite-model data and the station point in different directions.",
                     "short_series": "Too few years to judge."}[ev.reason]),
    ]

    prov = [dict(what=var.label, source=src, product=var.product, url=main_series.url,
                 retrieved_at=main_series.retrieved_at,
                 license="Public domain (NOAA)" if var.source_kind == "cag" else "Public domain (NASA)")]
    if witness and station is not None:
        prov.append(dict(what=f"{var.label} at weather station", source="NOAA NCEI",
                         product="Global Summary of the Month" if station.method == "gsom" else "GHCN-Daily → monthly",
                         url=station.url, retrieved_at=station.retrieved_at, license="Public domain (NOAA)"))

    det = ev.detection
    detection = dict(residual_sd=round(det.residual_sd, 4), phi=round(det.phi, 4),
                     slope_per_year=round(det.slope_per_year, 5), n_years=det.n_years,
                     multipliers=det.multipliers, years_needed=det.years_needed)

    extrapolation = build_extrapolation(
        slope_per_year=main.sen.slope_per_year, ci_low_per_year=main.sen.ci_low_per_year,
        ci_high_per_year=main.sen.ci_high_per_year, intercept_at_start=main.sen.intercept_at_start,
        start_year=start, end_year=end, decimals=d)

    scen = None
    if scenarios:
        base = [v for y, v in zip(years, vals) if 1995 <= y <= 2014 and v is not None]
        scen = dict(scenarios)
        if base and scen.get("baseline_value") is None:
            scen["baseline_value"] = round(sum(base) / len(base), d)
        if scen.get("baseline_value") is not None:
            scen = add_observed_context(scen, years, vals, d)
        for p in scenarios.get("provenance", []):
            prov.append(p)
        scen.pop("provenance", None)

    result = dict(
        case=dict(claim_text=spec.claim_text, variable_id=spec.variable_id, place=spec.place.model_dump(),
                  season=season, start_year=start, end_year=end, claim_direction=spec.claim_direction),
        variable=var.public().model_dump(),
        series=[dict(year=y, value=None if v is None else round(v, d)) for y, v in zip(years, vals)],
        sen=dict(slope_per_year=round(main.sen.slope_per_year, 5),
                 slope_per_decade=round(main.sen.slope_per_decade, 4),
                 ci_low=round(main.sen.ci_low_per_year * 10, 4), ci_high=round(main.sen.ci_high_per_year * 10, 4),
                 intercept=round(main.sen.intercept_at_start, 3)),
        mk=dict(p=sig3(main.mk.p), tau=round(main.mk.tau, 4), z=round(main.mk.z, 3), correction=main.mk.correction),
        ols=dict(slope_per_year=round(main.ols.slope_per_year, 5), p=sig3(main.ols.p),
                 r2=round(main.ols.r2, 4), n_eff=round(main.ols.n_eff, 1)),
        robustness=rob,
        robustness_summary=dict(significant=n_sig, total=len(rob)),
        witness=witness, verdict=ev.verdict, reason=ev.reason, years_to_wait=ev.years_to_wait,
        steps=steps, detection=detection, extrapolation=extrapolation, scenarios=scen, provenance=prov,
        meta=dict(stub=stub, stats_engine=STATS_ENGINE, generated_at=_now()),
    )
    return CheckResult.model_validate(result)


# ---------- live data ----------

def fetch_main_series(var: VariableDef, lat: float, lon: float, start: int, end: int) -> MainSeries:
    """Monthly series from the variable's source, starting in January of start-1 (for DJF)."""
    from .sources import giovanni, power

    first = max(start - 1, 1981)
    if var.source_kind == "power":
        pm = power.fetch_monthly(lat, lon, [var.source_param], first, end)
        return MainSeries(monthly=pm.series[var.source_param], start=pm.start, url=pm.url, retrieved_at=_now())
    g = giovanni.fetch_monthly(var.source_param, lat, lon, first, end)
    return MainSeries(monthly=g["monthly"], start=g["start"], url=g["url"], retrieved_at=_now())


def fetch_station(var: VariableDef, lat: float, lon: float, start: int, end: int) -> Optional[StationInput]:
    if not var.witness:
        return None
    from .sources import noaa

    st = noaa.best_station(lat, lon, var.witness, max(start - 1, 1981), end)
    if st is None:
        return None
    return StationInput(id=st.id, name=st.name, lat=st.lat, lon=st.lon, distance_km=st.distance_km,
                        monthly=st.monthly, start=st.start, method=st.method, url=st.url, retrieved_at=_now())


def fetch_cag_series(var: VariableDef, place, season) -> MainSeries:
    """Yearly land+ocean anomalies for a region (or the planet) from NOAA Climate at a Glance."""
    from .sources import cag

    c = cag.fetch_cag(region_key(place), season)
    return MainSeries(monthly=[], start="1850-01", url=c["url"], retrieved_at=_now(),
                      yearly=dict(zip(c["years"], c["anomaly"])))


def run_check(spec: CaseSpec) -> CheckResult:
    from .sources import SourceUnavailable

    var = validate_spec(spec)
    start = effective_start(spec.start_year, spec.season, var)
    lat, lon = spec.place.lat, spec.place.lon
    try:
        if var.source_kind == "cag":
            main_series = fetch_cag_series(var, spec.place, spec.season)
        else:
            main_series = fetch_main_series(var, lat, lon, start, spec.end_year)
    except SourceUnavailable as e:
        raise CheckError("source_unavailable", f"{SOURCE_LABEL[var.source_kind]} did not respond: {e.message}")
    try:
        station = fetch_station(var, lat, lon, start, spec.end_year)
    except SourceUnavailable:
        station = None  # the witness is optional; the verdict says "no station"
    scen = nearby_scenarios(spec.variable_id, spec.season, lat, lon)
    return assemble_result(spec, var, main_series, station, scenarios=scen)
