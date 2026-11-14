# Showcase pollutant events

Real monthly NASA satellite time series (`OMNO2d`, `OMSO2e`, `M2T1NXAER`) evaluated with the
BACI (Before–After–Control–Impact) pipeline (`backend/app/event.py`).

Placebo = fake event dates, every 12 months, whose shift is at least as large as the real one.
A verdict needs at least 3 fake dates. `aod` is MERRA-2, a model reanalysis.

| File | Event | Compound | Effect | % | p | 95% CI | Placebo | Verdict |
|---|---|---|---|---|---|---|---|---|
| `mundra-so2.json` | Mundra UMPP, India — Mundra UMPP coal power plant commissioning (2012-03, w=3y) | `so2` | +0.1428 DU | — | 0.00409 | [+0.049, +0.236] | 0/7 | `clear_change` (`clear_change`) |
| `sasan-no2.json` | Sasan UMPP, India — Sasan UMPP coal power plant commissioning (2013-08, w=3y) | `no2` | +1.3660 10¹⁵ molecules/cm² | +20.2% | 0.00409 | [+0.471, +2.262] | 1/7 | `not_proven` (`placebo_also_changes`) |
| `la-no2-lockdown.json` | Los Angeles, USA — COVID-19 stay-at-home order (2020-03, w=1y) | `no2` | -0.8760 10¹⁵ molecules/cm² | -12.0% | 0.0118 | [-1.494, -0.259] | 4/17 | `not_proven` (`placebo_also_changes`) |
| `burshtyn-aod.json` | Burshtyn, Ukraine — Burshtyn thermal power plant baseline check (2018-01, w=3y) | `aod` | -0.0003 AOD | -0.2% | 0.878 | [-0.004, +0.003] | 12/13 | `not_proven` (`not_significant`) |

## CO₂ global context & physics example

- **NOAA GML latest global monthly mean:** `2026-07` = **426.10 ppm** (YoY growth: +2.01 ppm/yr; 1980+ annual Sen slope: +1.906 ppm/yr, 95% CI [1.830, 1.970]).
- **10 Mt CO₂/yr × 30 years:** emits **0.30 Gt CO₂**, adding **0.01688 ppm** (0.01534–0.01841 ppm), radiative forcing **0.000212 W/m²**, and transient warming **0.000103 °C** (0.000073–0.000137 °C).

Regenerate: `backend/.venv/bin/python tools/build_events.py`
