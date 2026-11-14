"""Pollutant event impact pipeline (EventSpec -> EventResult) and CO2 physics API helpers."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Sequence

from .catalog import CompoundDef, get_compound
from .check import CheckError
from .models import (
    Co2GlobalSummary,
    Co2ImpactResult,
    Co2ImpactSpec,
    Co2Range,
    Compound,
    EventResult,
    EventSen,
    EventSpec,
    EventStep,
    Meta,
    MonthValue,
    PlaceboCheck,
    Provenance,
    WindowSummary,
)
from .stats.co2 import plant_contribution, summarize_global_co2, what_if_concentration
from .stats.event import EventStatsResult, analyze_event
from .verdict import sig3

EVENT_STATS_ENGINE = "backend.app.stats.event v1"
CO2_LICENSE = "Public domain (NOAA GML)"


@dataclass(frozen=True)
class EventSeriesInput:
    months: Sequence[str]
    site: Sequence[Optional[float]]
    control: Optional[Sequence[Optional[float]]]
    start: str
    url: str
    retrieved_at: str
    doi: Optional[str] = None
    request_strategy: str = "point_timeseries"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ym(ym: str) -> tuple[int, int]:
    parts = ym.split("-")
    if len(parts) != 2:
        raise CheckError("bad_request", f"Invalid event_month '{ym}'; expected YYYY-MM.")
    try:
        year, month = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise CheckError("bad_request", f"Invalid event_month '{ym}'; expected YYYY-MM.") from exc
    if not 1 <= month <= 12:
        raise CheckError("bad_request", f"Month in '{ym}' must be between 01 and 12.")
    return year, month


def validate_event_spec(spec: EventSpec) -> CompoundDef:
    compound = get_compound(spec.compound_id)
    if compound is None:
        raise CheckError("unknown_variable", f"Unknown compound '{spec.compound_id}'.")
    year, _ = _parse_ym(spec.event_month)
    if year < compound.first_year or year > compound.last_year:
        raise CheckError(
            "bad_request",
            f"{compound.label} covers {compound.first_year}–{compound.last_year}; event_month '{spec.event_month}' is outside that range.",
        )
    if not 1 <= spec.window_years <= 5:
        raise CheckError("bad_request", "window_years must be between 1 and 5.")
    return compound


def _round_opt(val: Optional[float], decimals: int) -> Optional[float]:
    return None if val is None else round(val, decimals)


def _format_steps(
    spec: EventSpec,
    compound: CompoundDef,
    data: EventSeriesInput,
    stats: EventStatsResult,
) -> list[EventStep]:
    d = compound.decimals
    u = compound.units
    valid_site = sum(v is not None for v in data.site)
    total_months = len(data.site)

    steps = [
        EventStep(
            id="data",
            title="Monthly satellite data",
            value=f"{valid_site} of {total_months} months",
            detail=f"Monthly {compound.label} at {spec.place.name} from {compound.product} ({data.months[0]} to {data.months[-1]}).",
        ),
        EventStep(
            id="seasons",
            title="Remove the seasons",
            value=f"{spec.window_years}-year baseline",
            detail=f"Each month is compared against its usual calendar-month level during the {spec.window_years} years before {spec.event_month}.",
        ),
        EventStep(
            id="control",
            title="Compare with the surroundings",
            value="8-point ring (~120 km)" if stats.control_used else "No surrounding control",
            detail=(
                "Subtracted regional swings measured across 8 points ~120 km away so wider weather or policy shifts cancel out."
                if stats.control_used
                else "Analyzed site anomalies alone without subtracting a surrounding ring (weaker evidence)."
            ),
        ),
    ]

    if stats.reason == "too_short" or stats.effect is None:
        steps.extend([
            EventStep(
                id="before_after",
                title="Before vs after",
                value="Too few valid months",
                detail=f"Need at least 60% valid months in both the {spec.window_years}-year before ({stats.before.n}) and after ({stats.after.n}) windows.",
            ),
            EventStep(
                id="chance",
                title="Could it be chance?",
                value="Not tested",
                detail="Skipped because one or both comparison windows had too many missing months.",
            ),
            EventStep(
                id="placebo",
                title="Fake dates check",
                value="Not tested",
                detail="Skipped because the main comparison window had too many missing months.",
            ),
            EventStep(
                id="verdict",
                title="Verdict",
                value="Not proven",
                detail="Not enough cloud-free monthly observations in the chosen before/after windows.",
            ),
        ])
        return steps

    rel_pct = f" ({stats.relative_change:+.1%})" if stats.relative_change is not None else ""
    steps.append(
        EventStep(
            id="before_after",
            title="Before vs after",
            value=f"{stats.effect:+.{d}f} {u}{rel_pct}",
            detail=(
                f"Comparing {stats.after.start}–{stats.after.end} (n={stats.after.n}) against "
                f"{stats.before.start}–{stats.before.end} (n={stats.before.n}) relative to surroundings."
            ),
        )
    )

    assert stats.p is not None and stats.ci_low is not None and stats.ci_high is not None
    p_str = f"p = {stats.p:.3f}" if stats.p >= 0.001 else "p < 0.001"
    sig = stats.p < 0.05 and (stats.ci_low > 0.0 or stats.ci_high < 0.0)
    steps.append(
        EventStep(
            id="chance",
            title="Could it be chance?",
            value=f"{p_str}, 95% CI [{stats.ci_low:+.{d}f}, {stats.ci_high:+.{d}f}]",
            detail=(
                "Autocorrelation-adjusted Welch t-test shows this shift is unlikely by random month-to-month swings."
                if sig
                else "Month-to-month persistence and noise can easily produce a difference this size."
            ),
        )
    )

    if not stats.placebo:
        placebo_val = "0 valid fake dates"
        placebo_detail = "No non-overlapping shifted dates fit inside the available record to rule out a pre-existing trend."
    else:
        placebo_val = f"{stats.placebo_larger} of {len(stats.placebo)} fake dates match"
        placebo_detail = (
            "No non-overlapping fake event date showed an equally large, significant jump."
            if stats.placebo_larger == 0
            else "At least one fake event date also shows a significant shift as large as the real date, pointing to a broader trend."
        )
    steps.append(
        EventStep(
            id="placebo",
            title="Fake dates check",
            value=placebo_val,
            detail=placebo_detail,
        )
    )

    verdict_label = "Clear change" if stats.verdict == "clear_change" else "Not proven"
    verdict_detail = {
        "clear_change": f"Significant {stats.direction} after {spec.event_month} vs surroundings, and fake dates do not show it.",
        "not_significant": "Difference after the event does not rise clearly above month-to-month noise.",
        "placebo_also_changes": "A change occurred, but fake event dates show just as big a shift, suggesting an ongoing trend rather than this event.",
        "no_placebo": "Not enough non-overlapping history to run the fake-dates placebo check.",
        "too_short": "Too few valid months in the before or after window.",
    }[stats.reason]
    steps.append(
        EventStep(
            id="verdict",
            title="Verdict",
            value=verdict_label,
            detail=verdict_detail,
        )
    )
    return steps


def assemble_event_result(
    spec: EventSpec,
    compound: CompoundDef,
    data: EventSeriesInput,
    *,
    stub: bool = False,
) -> EventResult:
    """Compute BACI statistics and build an EventResult from pre-fetched monthly series."""
    stats = analyze_event(
        site=data.site,
        control=data.control if spec.use_control else None,
        start_month=data.start,
        event_month=spec.event_month,
        window_years=spec.window_years,
    )

    d = compound.decimals
    effect_prec = max(d + 1, 3)

    site_series = [
        MonthValue(month=m, value=_round_opt(v, d))
        for m, v in zip(data.months, data.site)
    ]
    ctrl_series = (
        [MonthValue(month=m, value=_round_opt(v, d)) for m, v in zip(data.months, data.control)]
        if (spec.use_control and data.control is not None)
        else None
    )

    sen_b = (
        EventSen(
            slope_per_year=round(stats.sen_before.slope_per_year, effect_prec),
            ci_low=round(stats.sen_before.ci_low, effect_prec),
            ci_high=round(stats.sen_before.ci_high, effect_prec),
        )
        if stats.sen_before is not None
        else None
    )
    sen_after = (
        EventSen(
            slope_per_year=round(stats.sen_after.slope_per_year, effect_prec),
            ci_low=round(stats.sen_after.ci_low, effect_prec),
            ci_high=round(stats.sen_after.ci_high, effect_prec),
        )
        if stats.sen_after is not None
        else None
    )

    placebo_list = [
        PlaceboCheck(
            event_month=pl.event_month,
            effect=round(pl.effect, effect_prec),
            p=sig3(pl.p),
        )
        for pl in stats.placebo
    ]

    steps = _format_steps(spec, compound, data, stats)
    provenance = [
        Provenance(
            what=f"{compound.label} ({data.request_strategy})",
            source="NASA Giovanni",
            product=compound.product,
            url=data.url,
            retrieved_at=data.retrieved_at,
            license="Public domain (NASA)",
        )
    ]

    return EventResult(
        spec=spec,
        compound=compound.public(),
        site=site_series,
        control=ctrl_series,
        before=WindowSummary(
            start=stats.before.start,
            end=stats.before.end,
            mean=_round_opt(stats.before.mean, d),
            n=stats.before.n,
        ),
        after=WindowSummary(
            start=stats.after.start,
            end=stats.after.end,
            mean=_round_opt(stats.after.mean, d),
            n=stats.after.n,
        ),
        effect=_round_opt(stats.effect, effect_prec),
        ci_low=_round_opt(stats.ci_low, effect_prec),
        ci_high=_round_opt(stats.ci_high, effect_prec),
        bootstrap_ci_low=_round_opt(stats.bootstrap_ci_low, effect_prec),
        bootstrap_ci_high=_round_opt(stats.bootstrap_ci_high, effect_prec),
        p=None if stats.p is None else sig3(stats.p),
        relative_change=None if stats.relative_change is None else round(stats.relative_change, 4),
        placebo=placebo_list,
        placebo_larger=stats.placebo_larger,
        verdict=stats.verdict,
        direction=stats.direction,
        reason=stats.reason,
        sen_before=sen_b,
        sen_after=sen_after,
        steps=steps,
        provenance=provenance,
        meta=Meta(stub=stub, stats_engine=EVENT_STATS_ENGINE, generated_at=_now()),
    )


def fetch_event_series(
    compound: CompoundDef,
    lat: float,
    lon: float,
    *,
    use_control: bool = True,
) -> EventSeriesInput:
    """Fetch full-range monthly site (and optional 8-point control ring) series from Giovanni."""
    from .sources.pollutants import fetch_site_and_control

    fetched = fetch_site_and_control(
        compound.id,
        lat,
        lon,
        compound.first_year,
        compound.last_year,
        include_control=use_control,
    )
    return EventSeriesInput(
        months=fetched["months"],
        site=fetched["site"],
        control=fetched["control"],
        start=fetched["start"],
        url=fetched["url"],
        retrieved_at=_now(),
        doi=fetched.get("doi"),
        request_strategy=fetched.get("request_strategy", "point_timeseries"),
    )


def run_event(spec: EventSpec) -> EventResult:
    """Validate EventSpec, fetch satellite series via Giovanni, and return EventResult."""
    from .sources import SourceUnavailable

    compound = validate_event_spec(spec)
    try:
        series = fetch_event_series(
            compound,
            spec.place.lat,
            spec.place.lon,
            use_control=spec.use_control,
        )
    except SourceUnavailable as exc:
        raise CheckError("source_unavailable", f"NASA Giovanni did not respond: {exc.message}") from exc
    return assemble_event_result(spec, compound, series)


# ---------- CO2 global context & physics ----------

def fetch_global_co2_series() -> dict:
    from .sources.pollutants import fetch_noaa_co2

    return fetch_noaa_co2()


def get_global_co2_summary() -> tuple[Co2GlobalSummary, str]:
    """Fetch NOAA GML global CO2 series and summarize latest level, YoY growth, and 1980+ Sen slope."""
    from .sources import SourceUnavailable

    try:
        raw = fetch_global_co2_series()
    except SourceUnavailable as exc:
        raise CheckError("source_unavailable", f"NOAA GML did not respond: {exc.message}") from exc

    summary = summarize_global_co2(raw["months"], raw["values"], since_year=1980)
    series = [
        MonthValue(month=m, value=v)
        for m, v in zip(raw["months"], raw["values"])
        if int(m[:4]) >= 1980
    ]
    model = Co2GlobalSummary(
        latest_month=summary.latest_month,
        latest_ppm=round(summary.latest_ppm, 2),
        yoy_growth_ppm=None if summary.yoy_growth_ppm is None else round(summary.yoy_growth_ppm, 2),
        sen_slope_ppm_per_year=round(summary.sen_slope_ppm_per_year, 3),
        sen_ci_low=round(summary.sen_ci_low, 3),
        sen_ci_high=round(summary.sen_ci_high, 3),
        mk_p=sig3(summary.mk_p),
        series=series,
    )
    return model, raw["url"]


def run_co2_impact(spec: Co2ImpactSpec) -> Co2ImpactResult:
    """Compute a source's cumulative CO2 contribution, radiative forcing, and transient warming."""
    global_summary, noaa_url = get_global_co2_summary()
    contrib = plant_contribution(
        mt_co2_per_year=spec.mt_co2_per_year,
        years=spec.years,
        c_now_ppm=global_summary.latest_ppm,
    )

    what_if_f: Optional[float] = None
    what_if_w: Optional[Co2Range] = None
    if spec.what_if_ppm is not None:
        wi = what_if_concentration(spec.what_if_ppm, c0_ppm=spec.c0_ppm)
        what_if_f = round(wi.forcing_w_m2, 4)
        what_if_w = Co2Range(
            central=round(wi.transient_warming_c.central, 3),
            low=round(wi.transient_warming_c.low, 3),
            high=round(wi.transient_warming_c.high, 3),
        )

    label = spec.label or f"{spec.mt_co2_per_year:g} Mt CO₂/yr over {spec.years:g} years"
    explanation = (
        f"{label} emits {contrib.total_emitted_gt:.3f} Gt CO₂ in total. "
        f"Because about 44% (40%–48%) stays in the air while oceans and land absorb the rest, "
        f"global CO₂ rises by ~{contrib.added_ppm.central:.5f} ppm "
        f"(range {contrib.added_ppm.low:.5f}–{contrib.added_ppm.high:.5f} ppm) above today's {global_summary.latest_ppm:.2f} ppm. "
        f"That adds {contrib.added_forcing_w_m2.central:.6f} W/m² of radiative forcing and roughly "
        f"{contrib.transient_warming_c.central:.6f} °C of transient global warming "
        f"(likely range {contrib.transient_warming_c.low:.6f}–{contrib.transient_warming_c.high:.6f} °C)."
    )

    return Co2ImpactResult(
        spec=spec,
        total_emitted_gt=round(contrib.total_emitted_gt, 6),
        added_ppm=Co2Range(
            central=round(contrib.added_ppm.central, 6),
            low=round(contrib.added_ppm.low, 6),
            high=round(contrib.added_ppm.high, 6),
        ),
        added_forcing_w_m2=Co2Range(
            central=round(contrib.added_forcing_w_m2.central, 7),
            low=round(contrib.added_forcing_w_m2.low, 7),
            high=round(contrib.added_forcing_w_m2.high, 7),
        ),
        transient_warming_c=Co2Range(
            central=round(contrib.transient_warming_c.central, 7),
            low=round(contrib.transient_warming_c.low, 7),
            high=round(contrib.transient_warming_c.high, 7),
        ),
        what_if_forcing_w_m2=what_if_f,
        what_if_warming_c=what_if_w,
        global_co2=global_summary,
        explanation=explanation,
        provenance=[
            Provenance(
                what="Global monthly mean atmospheric CO2",
                source="NOAA GML",
                product="Globally averaged marine surface CO2 (co2_mm_gl.txt)",
                url=noaa_url,
                retrieved_at=_now(),
                license=CO2_LICENSE,
            )
        ],
    )
