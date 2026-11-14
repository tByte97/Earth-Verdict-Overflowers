#!/usr/bin/env python3
"""Build verified showcase pollutant event files (data/events/*.json) and data/events/README.md.

Uses the exact same backend pipeline (app.event.run_event & app.event.run_co2_impact)
as the live HTTP API, backed by cached NASA Giovanni and NOAA GML responses.

Run (from repository root):
  backend/.venv/bin/python tools/build_events.py
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.event import run_co2_impact, run_event  # noqa: E402
from app.models import Co2ImpactSpec, EventSpec, Place  # noqa: E402

EVENTS_DIR = ROOT / "data" / "events"

SHOWCASE_EVENTS = [
    (
        "mundra-so2",
        EventSpec(
            compound_id="so2",
            place=Place(place_id="ev:mundra", name="Mundra UMPP, India", lat=22.823, lon=69.553),
            event_month="2012-03",
            event_label="Mundra UMPP coal power plant commissioning",
            window_years=3,
            use_control=True,
        ),
    ),
    (
        "sasan-no2",
        EventSpec(
            compound_id="no2",
            place=Place(place_id="ev:sasan", name="Sasan UMPP, India", lat=23.978, lon=82.628),
            event_month="2013-08",
            event_label="Sasan UMPP coal power plant commissioning",
            window_years=3,
            use_control=True,
        ),
    ),
    (
        "la-no2-lockdown",
        EventSpec(
            compound_id="no2",
            place=Place(place_id="ev:la", name="Los Angeles, USA", lat=34.0522, lon=-118.2437),
            event_month="2020-03",
            event_label="COVID-19 stay-at-home order",
            window_years=1,
            use_control=True,
        ),
    ),
    (
        "burshtyn-aod",
        EventSpec(
            compound_id="aod",
            place=Place(place_id="ev:burshtyn", name="Burshtyn, Ukraine", lat=49.208, lon=24.664),
            event_month="2018-01",
            event_label="Burshtyn thermal power plant baseline check",
            window_years=3,
            use_control=True,
        ),
    ),
]


def _fmt_row(eid: str, r) -> str:
    eff = f"{r.effect:+.4f} {r.compound.units}" if r.effect is not None else "—"
    pct = f"{r.relative_change:+.1%}" if r.relative_change is not None else "—"
    p = f"{r.p:.3g}" if r.p is not None else "—"
    ci = f"[{r.ci_low:+.3f}, {r.ci_high:+.3f}]" if r.ci_low is not None else "—"
    pl = f"{r.placebo_larger}/{len(r.placebo)}"
    return (
        f"| `{eid}.json` | {r.spec.place.name} — {r.spec.event_label} ({r.spec.event_month}, w={r.spec.window_years}y) "
        f"| `{r.spec.compound_id}` | {eff} | {pct} | {p} | {ci} | {pl} | `{r.verdict}` (`{r.reason}`) |"
    )


def main() -> None:
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[str] = []

    for eid, spec in SHOWCASE_EVENTS:
        res = run_event(spec)
        out_path = EVENTS_DIR / f"{eid}.json"
        out_path.write_text(json.dumps(res.model_dump(mode="json"), ensure_ascii=False, indent=1), encoding="utf-8")
        rows.append(_fmt_row(eid, res))
        print(f"{eid}: {res.verdict} ({res.reason}), effect={res.effect}, p={res.p}")

    co2 = run_co2_impact(
        Co2ImpactSpec(
            mt_co2_per_year=10.0,
            years=30,
            what_if_ppm=560.0,
            c0_ppm=280.0,
            label="Example 10 Mt CO2/yr power plant over 30 years",
        )
    )

    readme = "\n".join([
        "# Showcase pollutant events",
        "",
        "Real monthly NASA satellite time series (`OMNO2d`, `OMSO2e`, `M2T1NXAER`) evaluated with the",
        "BACI (Before–After–Control–Impact) pipeline (`backend/app/event.py`).",
        "",
        "| File | Event | Compound | Effect | % | p | 95% CI | Placebo | Verdict |",
        "|---|---|---|---|---|---|---|---|---|",
        *rows,
        "",
        "## CO₂ global context & physics example",
        "",
        f"- **NOAA GML latest global monthly mean:** `{co2.global_co2.latest_month}` = **{co2.global_co2.latest_ppm:.2f} ppm** "
        f"(YoY growth: {co2.global_co2.yoy_growth_ppm:+.2f} ppm/yr; 1980+ annual Sen slope: "
        f"{co2.global_co2.sen_slope_ppm_per_year:+.3f} ppm/yr, 95% CI [{co2.global_co2.sen_ci_low:.3f}, {co2.global_co2.sen_ci_high:.3f}], p={co2.global_co2.mk_p:.4g}).",
        f"- **10 Mt CO₂/yr × 30 years:** emits **{co2.total_emitted_gt:.2f} Gt CO₂**, adding "
        f"**{co2.added_ppm.central:.5f} ppm** ({co2.added_ppm.low:.5f}–{co2.added_ppm.high:.5f} ppm), "
        f"radiative forcing **{co2.added_forcing_w_m2.central:.6f} W/m²**, and transient warming "
        f"**{co2.transient_warming_c.central:.6f} °C** ({co2.transient_warming_c.low:.6f}–{co2.transient_warming_c.high:.6f} °C).",
        "",
        "Regenerate: `backend/.venv/bin/python tools/build_events.py`",
        "",
    ])
    (EVENTS_DIR / "README.md").write_text(readme, encoding="utf-8")
    print(f"\nCO2 latest ({co2.global_co2.latest_month}): {co2.global_co2.latest_ppm} ppm, Sen={co2.global_co2.sen_slope_ppm_per_year}/yr")


if __name__ == "__main__":
    main()
