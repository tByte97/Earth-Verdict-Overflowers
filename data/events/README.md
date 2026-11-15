# Showcase pollutant events

Real monthly NASA satellite time series (`OMNO2d`, `OMSO2e`, `M2T1NXAER`) evaluated with the
BACI (Before–After–Control–Impact) pipeline (`backend/app/event.py`).

Placebo = fake event dates, every 12 months, whose shift is at least as large as the real one.
A verdict needs at least 3 fake dates. `aod` is MERRA-2, a model reanalysis.

| File | Event | Compound | Effect | % | p | 95% CI | Placebo | Verdict |
|---|---|---|---|---|---|---|---|---|
| `mundra-so2.json` | Mundra UMPP, India — Mundra coal power plant opens (India) (2012-03, w=3y) | `so2` | +0.1350 DU | — | 0.00177 | [+0.054, +0.216] | 0/7 | `clear_change` (`clear_change`) |
| `sasan-no2.json` | Sasan UMPP, India — Sasan coal power plant opens (India) (2013-08, w=3y) | `no2` | +1.2950 10¹⁵ molecules/cm² | +19.2% | 0.00615 | [+0.392, +2.199] | 1/7 | `not_proven` (`placebo_also_changes`) |
| `navajo-no2.json` | Navajo Generating Station, Page, Arizona — Navajo Generating Station closes (Arizona, USA) (2019-11, w=3y) | `no2` | -0.2670 10¹⁵ molecules/cm² | -22.8% | 1.43e-06 | [-0.366, -0.167] | 4/9 | `not_proven` (`placebo_also_changes`) |
| `la-no2-lockdown.json` | Los Angeles, USA — COVID-19 stay-at-home order (Los Angeles) (2020-03, w=1y) | `no2` | -0.7400 10¹⁵ molecules/cm² | -10.2% | 0.45 | [-2.941, +1.461] | 4/17 | `not_proven` (`not_significant`) |
| `burshtyn-aod.json` | Burshtyn, Ukraine — No event: Burshtyn power plant area (Ukraine) (2018-01, w=3y) | `aod` | -0.0003 AOD | -0.2% | 0.872 | [-0.004, +0.003] | 12/13 | `not_proven` (`not_significant`) |

## CO₂ global context & physics example

- **NOAA GML latest global monthly mean:** `2026-07` = **426.10 ppm** (YoY growth: +2.01 ppm/yr; 1980+ annual Sen slope: +1.906 ppm/yr, 95% CI [1.504, 2.336]).
- **10 Mt CO₂/yr × 30 years:** emits **0.30 Gt CO₂**, adding **0.01688 ppm** (0.01534–0.01841 ppm), radiative forcing **0.000212 W/m²**, and transient warming **0.000103 °C** (0.000073–0.000137 °C).

Regenerate: `backend/.venv/bin/python tools/build_events.py`
