# Showcase pollutant events

Real monthly NASA satellite time series (`OMNO2d`, `OMSO2e`, `M2T1NXAER`) evaluated with the
BACI (Before–After–Control–Impact) pipeline (`backend/app/event.py`).

| File | Event | Compound | Effect | % | p | 95% CI | Placebo | Verdict |
|---|---|---|---|---|---|---|---|---|
| `mundra-so2.json` | Mundra UMPP, India — Mundra UMPP coal power plant commissioning (2012-03, w=3y) | `so2` | +0.1424 DU | +238.6% | 0.00244 | [+0.054, +0.231] | 0/1 | `clear_change` (`clear_change`) |
| `sasan-no2.json` | Sasan UMPP, India — Sasan UMPP coal power plant commissioning (2013-08, w=3y) | `no2` | +1.3660 10¹⁵ molecules/cm² | +20.2% | 0.00251 | [+0.516, +2.217] | 0/1 | `clear_change` (`clear_change`) |
| `la-no2-lockdown.json` | Los Angeles, USA — COVID-19 stay-at-home order (2020-03, w=1y) | `no2` | -0.8700 10¹⁵ molecules/cm² | -11.9% | 0.00537 | [-1.411, -0.329] | 0/5 | `clear_change` (`clear_change`) |
| `burshtyn-aod.json` | Burshtyn, Ukraine — Burshtyn thermal power plant baseline check (2018-01, w=3y) | `aod` | -0.0003 AOD | -0.2% | 0.875 | [-0.004, +0.003] | 0/1 | `not_proven` (`not_significant`) |

## CO₂ global context & physics example

- **NOAA GML latest global monthly mean:** `2026-07` = **426.10 ppm** (YoY growth: +2.01 ppm/yr; 1980+ annual Sen slope: +1.906 ppm/yr, 95% CI [1.830, 1.970], p=0.0118).
- **10 Mt CO₂/yr × 30 years:** emits **0.30 Gt CO₂**, adding **0.01688 ppm** (0.01534–0.01841 ppm), radiative forcing **0.000212 W/m²**, and transient warming **0.000097 °C** (0.000069–0.000129 °C).

Regenerate: `backend/.venv/bin/python tools/build_events.py`
