# US State Climate Trend Ranking (1981–2025)

## Method (10 lines)
1. **Grids:** Fetch NASA POWER regional monthly data (`0.5° × 0.625°` MERRA-2 grid, 1981–2025) for the Lower 48 (`lat 24–50°, lon -125° to -66°`, 18 tiles) and Alaska (`lat 51–71.5°, lon -170° to -130°`, 12 tiles).
2. **Parameters:** `T2M` (2 m air temperature, `°C`), `PRECTOTCORR` (bias-corrected precipitation, `mm/day`), and `SNODP` (snow depth, `cm`); all 90 parameter-tiles succeeded with zero failures.
3. **State assignment:** Assign each unique grid cell (`7,765` total in the bounding boxes) by its cell centre `(lon, lat)` to US Census `cb_2018_us_state_20m` polygons via a pure-Python/NumPy even-odd ray-casting point-in-polygon test (`3,545` cells inside `49` states; offshore/Canada/Mexico cells ignored).
4. **Minimum sample filter:** Drop states with `< 4` grid cells (`DE`: 3 cells, `RI`: 1 cell; `DC`, `HI`, `PR`: 0 cells in the domains), leaving `47` states (`3,541` cells).
5. **Seasonal aggregation:** Aggregate monthly series per cell and season (`JJA`, `DJF`, `year`) identically to the app (`T2M` and `SNODP` seasonal mean; `PRECTOTCORR` summed after multiplying `mm/day` by calendar days in each month; `DJF` starts in 1982 using Dec of `Y-1`).
6. **Trend & significance:** Compute Sen's median pairwise slope (`×10` for per-decade rate) and autocorrelation-corrected Mann–Kendall `p`-value (`build_grid_trends.cell_trend` via `app.stats.trend.analyze_trend`: Hamed–Rao rank-ACF correction with an AR(1) floor).
7. **Multiple testing (BH-FDR):** Apply Benjamini–Hochberg FDR at `q = 0.05` (`backend/app/stats/fdr.py`) across all `m = 3,545` US-assigned cells per `(parameter, season)` family (`9` families total).
8. **State metrics:** For each `(state, parameter, season)`, compute `n_cells`, FDR-significant share (`share_sig_fdr`), median Sen slope over significant cells (`median_slope_sig`) and over all cells (`median_slope_all`), sign consistency (`max(n_pos, n_neg) / n_sig_fdr`), and `clarity_score = share_sig_fdr × consistency`.
9. **Rankings:** Rank states for temperature (`T2M`) per season and by mean clarity across `JJA + DJF + year`, flag precipitation (`PRECTOTCORR`) and snow (`SNODP`) trends separately, and identify null-example states/seasons.
10. **CMIP6 region selection:** Select 3 compact (`<= 10° × 25°`) bounding boxes for `tools/fetch_cmip6_region.py` that cover multi-state clusters with high clarity, strong slopes, and dense NOAA station coverage.

---

## 1. Temperature (`T2M`) Rankings

### Top-10 States per Season (`T2M`, `°C/decade`)

#### Summer (`JJA`, 1981–2025) — US-wide FDR significant: `2,053 / 3,545` cells (`57.9%`)
| Rank | State | `n_cells` | FDR Sig (`share`) | Median Slope Sig (`°C/dec`) | Median Slope All (`°C/dec`) | Consistency | Clarity Score |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | NV (Nevada) | 89 | 89 (100.0%) | +0.614 | +0.614 | 1.00 | **1.000** |
| 2 | UT (Utah) | 71 | 71 (100.0%) | +0.558 | +0.558 | 1.00 | **1.000** |
| 3 | NM (New Mexico) | 96 | 96 (100.0%) | +0.542 | +0.542 | 1.00 | **1.000** |
| 4 | AZ (Arizona) | 97 | 97 (100.0%) | +0.509 | +0.509 | 1.00 | **1.000** |
| 5 | MA (Massachusetts) | 6 | 6 (100.0%) | +0.454 | +0.454 | 1.00 | **1.000** |
| 6 | CT (Connecticut) | 6 | 6 (100.0%) | +0.445 | +0.445 | 1.00 | **1.000** |
| 7 | NJ (New Jersey) | 8 | 8 (100.0%) | +0.396 | +0.396 | 1.00 | **1.000** |
| 8 | NY (New York) | 46 | 46 (100.0%) | +0.387 | +0.387 | 1.00 | **1.000** |
| 9 | VT (Vermont) | 12 | 12 (100.0%) | +0.383 | +0.383 | 1.00 | **1.000** |
| 10 | NH (New Hampshire) | 8 | 8 (100.0%) | +0.375 | +0.375 | 1.00 | **1.000** |

#### Winter (`DJF`, 1982–2025) — US-wide FDR significant: `1,631 / 3,545` cells (`46.0%`)
| Rank | State | `n_cells` | FDR Sig (`share`) | Median Slope Sig (`°C/dec`) | Median Slope All (`°C/dec`) | Consistency | Clarity Score |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | ME (Maine) | 32 | 32 (100.0%) | +0.650 | +0.650 | 1.00 | **1.000** |
| 2 | VT (Vermont) | 12 | 12 (100.0%) | +0.648 | +0.648 | 1.00 | **1.000** |
| 3 | SC (South Carolina) | 25 | 25 (100.0%) | +0.645 | +0.645 | 1.00 | **1.000** |
| 4 | VA (Virginia) | 27 | 27 (100.0%) | +0.609 | +0.609 | 1.00 | **1.000** |
| 5 | NH (New Hampshire) | 8 | 8 (100.0%) | +0.577 | +0.577 | 1.00 | **1.000** |
| 6 | TN (Tennessee) | 42 | 42 (100.0%) | +0.574 | +0.574 | 1.00 | **1.000** |
| 7 | MD (Maryland) | 9 | 9 (100.0%) | +0.537 | +0.537 | 1.00 | **1.000** |
| 8 | WV (West Virginia) | 21 | 21 (100.0%) | +0.535 | +0.535 | 1.00 | **1.000** |
| 9 | CT (Connecticut) | 6 | 6 (100.0%) | +0.520 | +0.520 | 1.00 | **1.000** |
| 10 | NJ (New Jersey) | 8 | 8 (100.0%) | +0.495 | +0.495 | 1.00 | **1.000** |

#### Whole Year (`year`, 1981–2025) — US-wide FDR significant: `3,173 / 3,545` cells (`89.5%`)
| Rank | State | `n_cells` | FDR Sig (`share`) | Median Slope Sig (`°C/dec`) | Median Slope All (`°C/dec`) | Consistency | Clarity Score |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | NM (New Mexico) | 96 | 96 (100.0%) | +0.483 | +0.483 | 1.00 | **1.000** |
| 2 | NV (Nevada) | 89 | 89 (100.0%) | +0.477 | +0.477 | 1.00 | **1.000** |
| 3 | AZ (Arizona) | 97 | 97 (100.0%) | +0.465 | +0.465 | 1.00 | **1.000** |
| 4 | UT (Utah) | 71 | 71 (100.0%) | +0.455 | +0.455 | 1.00 | **1.000** |
| 5 | VT (Vermont) | 12 | 12 (100.0%) | +0.449 | +0.449 | 1.00 | **1.000** |
| 6 | MD (Maryland) | 9 | 9 (100.0%) | +0.437 | +0.437 | 1.00 | **1.000** |
| 7 | NJ (New Jersey) | 8 | 8 (100.0%) | +0.423 | +0.423 | 1.00 | **1.000** |
| 8 | VA (Virginia) | 27 | 27 (100.0%) | +0.422 | +0.422 | 1.00 | **1.000** |
| 9 | CT (Connecticut) | 6 | 6 (100.0%) | +0.422 | +0.422 | 1.00 | **1.000** |
| 10 | NH (New Hampshire) | 8 | 8 (100.0%) | +0.421 | +0.421 | 1.00 | **1.000** |

---

### Overall Temperature (`T2M`) Ranking Across All 47 States (`JJA + DJF + year`)

Each seasonal cell shows `clarity_score (median_slope_sig / median_slope_all)` in `°C/decade`.

| Rank | State | `n_cells` | Mean Clarity (`JJA+DJF+year`) | `JJA` Clarity (`sig / all °C/dec`) | `DJF` Clarity (`sig / all °C/dec`) | `year` Clarity (`sig / all °C/dec`) |
|---:|---|---:|---:|---|---|---|
| 1 | VT (Vermont) | 12 | **1.000** | 1.000 (+0.383 / +0.383) | 1.000 (+0.648 / +0.648) | 1.000 (+0.449 / +0.449) |
| 2 | MD (Maryland) | 9 | **1.000** | 1.000 (+0.375 / +0.375) | 1.000 (+0.537 / +0.537) | 1.000 (+0.437 / +0.437) |
| 3 | NJ (New Jersey) | 8 | **1.000** | 1.000 (+0.396 / +0.396) | 1.000 (+0.495 / +0.495) | 1.000 (+0.423 / +0.423) |
| 4 | CT (Connecticut) | 6 | **1.000** | 1.000 (+0.445 / +0.445) | 1.000 (+0.520 / +0.520) | 1.000 (+0.422 / +0.422) |
| 5 | NH (New Hampshire) | 8 | **1.000** | 1.000 (+0.375 / +0.375) | 1.000 (+0.577 / +0.577) | 1.000 (+0.421 / +0.421) |
| 6 | ME (Maine) | 32 | **1.000** | 1.000 (+0.314 / +0.314) | 1.000 (+0.650 / +0.650) | 1.000 (+0.415 / +0.415) |
| 7 | NM (New Mexico) | 96 | **0.972** | 1.000 (+0.542 / +0.542) | 0.917 (+0.393 / +0.391) | 1.000 (+0.483 / +0.483) |
| 8 | VA (Virginia) | 27 | **0.951** | 0.852 (+0.289 / +0.275) | 1.000 (+0.609 / +0.609) | 1.000 (+0.422 / +0.422) |
| 9 | MA (Massachusetts) | 6 | **0.944** | 1.000 (+0.454 / +0.454) | 0.833 (+0.541 / +0.534) | 1.000 (+0.420 / +0.420) |
| 10 | WV (West Virginia) | 21 | **0.937** | 0.809 (+0.310 / +0.304) | 1.000 (+0.535 / +0.535) | 1.000 (+0.382 / +0.382) |
| 11 | AZ (Arizona) | 97 | **0.907** | 1.000 (+0.509 / +0.509) | 0.722 (+0.387 / +0.372) | 1.000 (+0.465 / +0.465) |
| 12 | TX (Texas) | 207 | **0.902** | 0.730 (+0.381 / +0.332) | 0.976 (+0.442 / +0.441) | 1.000 (+0.378 / +0.378) |
| 13 | FL (Florida) | 43 | **0.891** | 0.977 (+0.265 / +0.265) | 0.698 (+0.406 / +0.381) | 1.000 (+0.349 / +0.349) |
| 14 | PA (Pennsylvania) | 35 | **0.848** | 1.000 (+0.374 / +0.374) | 0.543 (+0.486 / +0.470) | 1.000 (+0.406 / +0.406) |
| 15 | NV (Nevada) | 89 | **0.843** | 1.000 (+0.614 / +0.614) | 0.528 (+0.295 / +0.280) | 1.000 (+0.477 / +0.477) |
| 16 | NY (New York) | 46 | **0.833** | 1.000 (+0.387 / +0.387) | 0.500 (+0.507 / +0.461) | 1.000 (+0.412 / +0.412) |
| 17 | OH (Ohio) | 36 | **0.824** | 0.778 (+0.328 / +0.316) | 0.694 (+0.495 / +0.489) | 1.000 (+0.371 / +0.371) |
| 18 | UT (Utah) | 71 | **0.817** | 1.000 (+0.558 / +0.558) | 0.451 (+0.350 / +0.342) | 1.000 (+0.455 / +0.455) |
| 19 | LA (Louisiana) | 41 | **0.805** | 0.488 (+0.266 / +0.230) | 0.927 (+0.438 / +0.436) | 1.000 (+0.316 / +0.316) |
| 20 | NC (North Carolina) | 46 | **0.804** | 0.522 (+0.229 / +0.218) | 0.891 (+0.637 / +0.627) | 1.000 (+0.398 / +0.398) |
| 21 | AL (Alabama) | 45 | **0.763** | 0.311 (+0.278 / +0.193) | 0.978 (+0.552 / +0.551) | 1.000 (+0.355 / +0.355) |
| 22 | IN (Indiana) | 36 | **0.759** | 0.583 (+0.337 / +0.293) | 0.694 (+0.601 / +0.575) | 1.000 (+0.385 / +0.385) |
| 23 | IL (Illinois) | 49 | **0.741** | 0.490 (+0.299 / +0.237) | 0.735 (+0.567 / +0.569) | 1.000 (+0.365 / +0.365) |
| 24 | WY (Wyoming) | 88 | **0.739** | 0.943 (+0.432 / +0.427) | 0.273 (+0.455 / +0.327) | 1.000 (+0.374 / +0.374) |
| 25 | SC (South Carolina) | 25 | **0.733** | 0.200 (+0.200 / +0.208) | 1.000 (+0.645 / +0.645) | 1.000 (+0.388 / +0.388) |
| 26 | CA (California) | 134 | **0.721** | 0.843 (+0.602 / +0.569) | 0.440 (+0.360 / +0.238) | 0.881 (+0.436 / +0.417) |
| 27 | GA (Georgia) | 46 | **0.717** | 0.174 (+0.230 / +0.216) | 0.978 (+0.576 / +0.571) | 1.000 (+0.365 / +0.365) |
| 28 | MS (Mississippi) | 34 | **0.716** | 0.147 (+0.229 / +0.126) | 1.000 (+0.493 / +0.493) | 1.000 (+0.300 / +0.300) |
| 29 | OR (Oregon) | 93 | **0.713** | 0.979 (+0.557 / +0.555) | 0.258 (+0.274 / +0.186) | 0.903 (+0.350 / +0.335) |
| 30 | ID (Idaho) | 83 | **0.711** | 0.988 (+0.495 / +0.494) | 0.193 (+0.377 / +0.273) | 0.952 (+0.344 / +0.338) |
| 31 | MO (Missouri) | 66 | **0.707** | 0.500 (+0.334 / +0.241) | 0.621 (+0.527 / +0.501) | 1.000 (+0.347 / +0.347) |
| 32 | AR (Arkansas) | 39 | **0.701** | 0.103 (+0.147 / +0.142) | 1.000 (+0.488 / +0.488) | 1.000 (+0.300 / +0.300) |
| 33 | CO (Colorado) | 95 | **0.698** | 0.990 (+0.420 / +0.419) | 0.116 (+0.310 / +0.187) | 0.990 (+0.330 / +0.327) |
| 34 | OK (Oklahoma) | 54 | **0.679** | 0.148 (+0.326 / +0.230) | 0.889 (+0.498 / +0.482) | 1.000 (+0.356 / +0.356) |
| 35 | TN (Tennessee) | 42 | **0.675** | 0.024 (+0.117 / +0.139) | 1.000 (+0.574 / +0.574) | 1.000 (+0.336 / +0.336) |
| 36 | MI (Michigan) | 55 | **0.594** | 0.673 (+0.348 / +0.274) | 0.109 (+0.515 / +0.415) | 1.000 (+0.318 / +0.318) |
| 37 | KY (Kentucky) | 32 | **0.583** | 0.000 (— / +0.143) | 0.750 (+0.556 / +0.552) | 1.000 (+0.319 / +0.319) |
| 38 | IA (Iowa) | 51 | **0.582** | 0.882 (+0.339 / +0.331) | 0.000 (— / +0.471) | 0.863 (+0.379 / +0.374) |
| 39 | WA (Washington) | 69 | **0.570** | 0.957 (+0.449 / +0.448) | 0.029 (+0.297 / +0.230) | 0.725 (+0.281 / +0.253) |
| 40 | AK (Alaska) | 915 | **0.514** | 0.325 (+0.251 / +0.174) | 0.345 (+0.575 / +0.471) | 0.871 (+0.430 / +0.388) |
| 41 | KS (Kansas) | 80 | **0.471** | 0.212 (+0.312 / +0.270) | 0.212 (+0.400 / +0.223) | 0.988 (+0.292 / +0.292) |
| 42 | NE (Nebraska) | 60 | **0.456** | 0.567 (+0.329 / +0.289) | 0.000 (— / +0.168) | 0.800 (+0.285 / +0.272) |
| 43 | MN (Minnesota) | 80 | **0.450** | 0.412 (+0.271 / +0.264) | 0.013 (+0.608 / +0.488) | 0.925 (+0.351 / +0.345) |
| 44 | WI (Wisconsin) | 52 | **0.436** | 0.231 (+0.328 / +0.191) | 0.077 (+0.589 / +0.568) | 1.000 (+0.323 / +0.323) |
| 45 | MT (Montana) | 139 | **0.317** | 0.540 (+0.361 / +0.271) | 0.007 (+0.362 / +0.143) | 0.403 (+0.274 / +0.208) |
| 46 | SD (South Dakota) | 70 | **0.248** | 0.371 (+0.295 / +0.249) | 0.000 (— / +0.113) | 0.371 (+0.290 / +0.235) |
| 47 | ND (North Dakota) | 73 | **0.100** | 0.014 (+0.198 / +0.198) | 0.000 (— / +0.184) | 0.288 (+0.260 / +0.197) |

---

## 2. Precipitation (`PRECTOTCORR`) & Snow Depth (`SNODP`) Rankings

Precipitation and snow-depth trends survive US-wide BH-FDR (`q = 0.05`) much more selectively than temperature:
- **`PRECTOTCORR` FDR-significant cells:** `258 / 3,545` (`7.3%`) in `JJA`, `185 / 3,545` (`5.2%`) in `DJF`, `474 / 3,545` (`13.4%`) in `year`.
- **`SNODP` FDR-significant cells:** `9 / 3,545` (`0.3%`) in `JJA`, `411 / 3,545` (`11.6%`) in `DJF`, `642 / 3,545` (`18.1%`) in `year`.

### Top Precipitation (`PRECTOTCORR`, `mm/decade`) States by Season

| Season | Rank | State | `n_cells` | FDR Sig (`share`) | Median Slope Sig (`mm/dec`) | Median Slope All (`mm/dec`) | Sign | Consistency | Clarity Score |
|---|---:|---|---:|---:|---:|---:|:---:|---:|---:|
| **year** | 1 | NM (New Mexico) | 96 | 56 (58.3%) | -32.193 | -28.776 | `-` | 1.00 | **0.583** |
| **year** | 2 | UT (Utah) | 71 | 37 (52.1%) | -28.917 | -20.583 | `-` | 1.00 | **0.521** |
| **year** | 3 | AZ (Arizona) | 97 | 35 (36.1%) | -36.401 | -18.916 | `-` | 1.00 | **0.361** |
| **year** | 4 | KY (Kentucky) | 32 | 11 (34.4%) | +30.779 | +27.910 | `+` | 1.00 | **0.344** |
| **year** | 5 | NY (New York) | 46 | 17 (37.0%) | +34.382 | +20.962 | `+` | 0.88 | **0.326** |
| **year** | 6 | AK (Alaska) | 915 | 184 (20.1%) | +34.198 | +20.582 | `+` | 1.00 | **0.201** |
| **year** | 7 | OR (Oregon) | 93 | 19 (20.4%) | -91.888 | -14.432 | `-` | 0.95 | **0.194** |
| **year** | 8 | WA (Washington) | 69 | 10 (14.5%) | -62.096 | -6.626 | `-` | 1.00 | **0.145** |
| **JJA** | 1 | OR (Oregon) | 93 | 50 (53.8%) | -10.533 | -8.089 | `-` | 1.00 | **0.538** |
| **JJA** | 2 | WA (Washington) | 69 | 24 (34.8%) | -9.947 | -8.969 | `-` | 1.00 | **0.348** |
| **JJA** | 3 | NY (New York) | 46 | 14 (30.4%) | +22.519 | +14.167 | `+` | 1.00 | **0.304** |
| **JJA** | 4 | MA (Massachusetts) | 6 | 1 (16.7%) | +13.173 | +0.733 | `+` | 1.00 | **0.167** |
| **JJA** | 5 | CT (Connecticut) | 6 | 1 (16.7%) | +11.861 | +0.258 | `+` | 1.00 | **0.167** |
| **JJA** | 6 | NJ (New Jersey) | 8 | 1 (12.5%) | +14.762 | +13.084 | `+` | 1.00 | **0.125** |
| **JJA** | 7 | AK (Alaska) | 915 | 107 (11.7%) | +17.232 | +11.883 | `+` | 1.00 | **0.117** |
| **DJF** | 1 | NM (New Mexico) | 96 | 36 (37.5%) | -5.883 | -5.224 | `-` | 1.00 | **0.375** |
| **DJF** | 2 | ME (Maine) | 32 | 9 (28.1%) | +12.697 | +14.570 | `+` | 1.00 | **0.281** |
| **DJF** | 3 | TX (Texas) | 207 | 52 (25.1%) | -6.913 | -8.177 | `-` | 1.00 | **0.251** |
| **DJF** | 4 | NH (New Hampshire) | 8 | 2 (25.0%) | +11.165 | +8.606 | `+` | 1.00 | **0.250** |
| **DJF** | 5 | CT (Connecticut) | 6 | 1 (16.7%) | +10.069 | +6.254 | `+` | 1.00 | **0.167** |
| **DJF** | 6 | VT (Vermont) | 12 | 2 (16.7%) | +4.400 | +3.992 | `+` | 1.00 | **0.167** |

### Top Snow Depth (`SNODP`, `cm/decade`) States by Season

| Season | Rank | State | `n_cells` | FDR Sig (`share`) | Median Slope Sig (`cm/dec`) | Median Slope All (`cm/dec`) | Sign | Consistency | Clarity Score |
|---|---:|---|---:|---:|---:|---:|:---:|---:|---:|
| **DJF** | 1 | GA (Georgia) | 46 | 39 (84.8%) | -0.576 | -0.491 | `-` | 1.00 | **0.848** |
| **DJF** | 2 | SC (South Carolina) | 25 | 20 (80.0%) | -0.728 | -0.664 | `-` | 1.00 | **0.800** |
| **DJF** | 3 | NC (North Carolina) | 46 | 28 (60.9%) | -1.063 | -0.949 | `-` | 1.00 | **0.609** |
| **DJF** | 4 | AL (Alabama) | 45 | 25 (55.6%) | -0.606 | -0.448 | `-` | 1.00 | **0.556** |
| **DJF** | 5 | TN (Tennessee) | 42 | 20 (47.6%) | -0.726 | -0.653 | `-` | 1.00 | **0.476** |
| **DJF** | 6 | IL (Illinois) | 49 | 21 (42.9%) | -0.509 | -0.497 | `-` | 1.00 | **0.429** |
| **DJF** | 7 | KY (Kentucky) | 32 | 12 (37.5%) | -0.913 | -0.827 | `-` | 1.00 | **0.375** |
| **DJF** | 8 | VA (Virginia) | 27 | 10 (37.0%) | -1.086 | -0.922 | `-` | 1.00 | **0.370** |
| **DJF** | 9 | OK (Oklahoma) | 54 | 20 (37.0%) | -0.627 | -0.637 | `-` | 1.00 | **0.370** |
| **DJF** | 10 | MO (Missouri) | 66 | 23 (34.8%) | -0.596 | -0.587 | `-` | 1.00 | **0.348** |
| **year** | 1 | GA (Georgia) | 46 | 42 (91.3%) | -0.123 | -0.116 | `-` | 1.00 | **0.913** |
| **year** | 2 | VA (Virginia) | 27 | 24 (88.9%) | -0.320 | -0.310 | `-` | 1.00 | **0.889** |
| **year** | 3 | WV (West Virginia) | 21 | 17 (81.0%) | -0.266 | -0.247 | `-` | 1.00 | **0.810** |
| **year** | 4 | KY (Kentucky) | 32 | 24 (75.0%) | -0.280 | -0.263 | `-` | 1.00 | **0.750** |
| **year** | 5 | SC (South Carolina) | 25 | 16 (64.0%) | -0.196 | -0.161 | `-` | 1.00 | **0.640** |
| **year** | 6 | NC (North Carolina) | 46 | 26 (56.5%) | -0.309 | -0.244 | `-` | 1.00 | **0.565** |
| **year** | 7 | OH (Ohio) | 36 | 18 (50.0%) | -0.296 | -0.224 | `-` | 1.00 | **0.500** |
| **year** | 8 | AL (Alabama) | 45 | 22 (48.9%) | -0.176 | -0.103 | `-` | 1.00 | **0.489** |
| **year** | 9 | TN (Tennessee) | 42 | 20 (47.6%) | -0.233 | -0.205 | `-` | 1.00 | **0.476** |
| **year** | 10 | NM (New Mexico) | 96 | 44 (45.8%) | -0.296 | -0.221 | `-` | 1.00 | **0.458** |
| **JJA** | 1 | WY (Wyoming) | 88 | 2 (2.3%) | -0.010 | +0.000 | `-` | 1.00 | **0.023** |
| **JJA** | 2 | AK (Alaska) | 915 | 7 (0.8%) | -0.354 | -0.006 | `-` | 1.00 | **0.008** |

> **Physical note on `SNODP`:** The highest spatial clarity in `SNODP` loss occurs along the Southern Appalachians, Piedmont, and Ohio/Middle Mississippi valleys (`GA`, `SC`, `NC`, `VA`, `WV`, `KY`, `TN`, `IL`), where winter warming of `+0.50` to `+0.65 °C/decade` across the `0 °C` isotherm has eliminated regular 1980s/1990s MERRA-2 winter snowpack events (`-0.5` to `-1.1 cm/decade` in `DJF`). By contrast, high-mountain Western states (`ID` `-6.47 cm/decade`, `WA` `-3.29 cm/decade`, `WY` `-2.01 cm/decade` in FDR-significant `DJF` cells) experience much larger absolute snowpack losses in individual mountain cells, but higher interannual variability leaves only `9–10%` of cells FDR-significant in `DJF` (`33.8%` in `UT`, `33.7%` in `NV`, and `45.8%` in `NM` for `year`).

---

## 3. Honest List of Null Examples & Surprising Non-Significant Regions

While every state (`47/47`) has at least some FDR-significant annual (`year`) `T2M` warming cells, several prominent regions and parameter/season combinations have **zero (`0.0%`) or near-zero FDR-significant cells** and serve as rigorous null / "noisy series" test cases for the app:

1. **Zero FDR-significant `T2M` cells (`clarity_score = 0.000`):**
   - **Northern Great Plains & Upper Midwest in Winter (`DJF` `T2M`):**
     - **`ND` (North Dakota, `n=73`):** `0/73` (`0.0%`) significant in `DJF` (median slope `+0.184 °C/decade`), `1/73` (`1.4%`) in `JJA`, and only `21/73` (`28.8%`) in `year` — the lowest overall temperature clarity in the US (`mean_clarity = 0.100`). Across all 9 `(parameter × season)` combinations, only `3.7%` of cell-seasons in `ND` are FDR-significant.
     - **`SD` (South Dakota, `n=70`):** `0/70` (`0.0%`) significant in `DJF` (median slope `+0.113 °C/decade`), `26/70` (`37.1%`) in `JJA` and `year` (`mean_clarity = 0.248`, #46 of 47).
     - **`NE` (Nebraska, `n=60`):** `0/60` (`0.0%`) significant in `DJF` (median slope `+0.168 °C/decade`).
     - **`IA` (Iowa, `n=51`):** `0/51` (`0.0%`) significant in `DJF` despite a large positive median slope (`+0.471 °C/decade`), because multi-degree interannual winter variance (`σ ~ 2.5–3.0 °C`) swamps the 44-winter record (`MN` has `1/80 = 1.3%` in `DJF` at `+0.488 °C/decade`; `MT` has `1/139 = 0.7%` in `DJF`).
   - **Central/Southeast US "Summer Warming Hole" (`JJA` `T2M`):**
     - **`KY` (Kentucky, `n=32`):** `0/32` (`0.0%`) significant in `JJA` (`median_slope_all = +0.143 °C/decade`), vs `75.0%` in `DJF` (`+0.552 °C/decade`) and `100.0%` in `year`.
     - **`TN` (Tennessee, `n=42`):** Only `1/42` (`2.4%`) significant in `JJA` (`+0.139 °C/decade`), vs `100.0%` in `DJF` (`+0.574 °C/decade`).
     - **`AR` (`10.3%` in `JJA`), `MS` (`14.7%` in `JJA`), `OK` (`14.8%` in `JJA`), `GA` (`17.4%` in `JJA`), `SC` (`20.0%` in `JJA`):** Classic southeastern/central US summer "warming hole" where summer warming since 1981 is weak and statistically non-significant in `80–100%` of cells, whereas winter (`DJF`) warming is `89–100%` FDR-significant.
2. **Surprising Partial-Significance Famous-Warming Regions:**
   - **`AK` (Alaska, `n=915`):** Ranked #40 of 47 in overall temperature clarity (`mean_clarity = 0.514`). Annual warming is widespread (`797/915 = 87.1%` FDR-significant, `+0.388 °C/decade` across all cells, up to `> +0.8 °C/decade` on the North Slope), and winter slopes are steep (`+0.471 °C/decade` median across all cells), but strong Pacific Decadal Oscillation (PDO) / Arctic Oscillation winter variability leaves only `34.5%` (`316/915`) of `DJF` cells and `32.5%` (`297/915`) of `JJA` cells significant after FDR.
   - **`CO` (Colorado, `n=95`) & `WA` (Washington, `n=69`) in `DJF`:** Near-100% clarity in summer (`CO` `99.0%`, `WA` `95.7%`), but winter `DJF` clarity drops to `11.6%` in `CO` and `2.9%` (`2/69`) in `WA`.
3. **States with 0 FDR-Significant Precipitation (`PRECTOTCORR`) Cells in ANY Season (`JJA`, `DJF`, `year`):**
   - `7` states have `0` FDR-significant precipitation cells across all three seasons: **`AL`, `IL`, `MD`, `MS`, `NC`, `OH`, `SC`** (and another 11 states have `<= 2` significant cell-seasons total: `AR`, `DE`, `GA`, `IA`, `IN`, `LA`, `MI`, `MN`, `MO`, `NE`, `PA`, `SD`, `WI`, `WV`).
4. **States with 0 FDR-Significant Snow Depth (`SNODP`) Cells in ANY Season (`JJA`, `DJF`, `year`):**
   - `3` states have `0` FDR-significant `SNODP` cells in any season: **`MD`, `NH`, `NJ`** (`MD` has `0` significant cells in both `PRECTOTCORR` and `SNODP` across all seasons, while having `100%` significant `T2M` in all seasons).

---

## 4. Three Recommended CMIP6 Regional Download Boxes

For `tools/fetch_cmip6_region.py` (`0.25°` NEX-GDDP-CMIP6 grid; reference Ukraine+Poland box is `9° × 21° = 37 × 85 = 3,145` cells `≈ 5 h`), each recommended box below is kept strictly `<= 10° × 17°` (`2,257` to `2,829` cells, i.e. `0.72×` to `0.90×` the Ukraine+Poland download cost):

| Box | Region Name | `south, west, north, east` (deg) | Span (`lat × lon`) | `0.25°` Grid (`n_lat × n_lon = cells`) | Cost vs UA+PL (`3,145` cells) | States Covered |
|---:|---|---|---|---:|---:|---|
| **1** | **Northeast & Mid-Atlantic Corridor** | `37.5, -83.0, 47.5, -66.5` | `10.0° × 16.5°` | `41 × 67 = 2,747` | `0.87×` (~4.4 h) | `ME, NH, VT, MA, CT, RI, NY, NJ, PA, DE, MD, DC, VA, WV` (+ eastern `OH`) |
| **2** | **American Southwest (Four Corners & Great Basin)** | `31.25, -120.0, 41.25, -103.0` | `10.0° × 17.0°` | `41 × 69 = 2,829` | `0.90×` (~4.5 h) | `NV, UT, AZ, NM, CO` (+ inland `CA`) |
| **3** | **Southeast & Southern Appalachians** | `30.5, -90.5, 39.5, -75.5` | `9.0° × 15.0°` | `37 × 61 = 2,257` | `0.72×` (~3.6 h) | `SC, NC, GA, AL, MS, TN, KY, VA, WV` (+ `MD, DE`) |

### Why These 3 Boxes?

1. **Box 1 — Northeast & Mid-Atlantic (`37.5, -83.0, 47.5, -66.5` → `2,747` cells at `0.25°`):**
   - Covers **all 6 states in the US with a perfect `1.000` temperature clarity score in every season (`JJA`, `DJF`, `year`)**: `VT` (`1.000`, `DJF +0.648`, `year +0.449 °C/dec`), `MD` (`1.000`, `DJF +0.537`, `year +0.437 °C/dec`), `NJ` (`1.000`, `DJF +0.495`, `year +0.423 °C/dec`), `CT` (`1.000`, `DJF +0.520`, `year +0.422 °C/dec`), `NH` (`1.000`, `DJF +0.577`, `year +0.421 °C/dec`), and `ME` (`1.000`, `DJF +0.650 °C/dec` — #1 winter warming rate in the US), plus #8 `VA` (`0.951`), #9 `MA` (`0.944`), #10 `WV` (`0.937`), #14 `PA` (`0.848`), and #16 `NY` (`0.833`).
   - Captures the **strongest wetting precipitation signals** in the US: `NY` (`PRECTOTCORR year` clarity `0.326`, `+34.38 mm/dec` sig; `JJA` clarity `0.304`, `+22.52 mm/dec` sig), `ME` (`DJF` clarity `0.281`, `+12.70 mm/dec` sig), and `NH` (`DJF` clarity `0.250`, `+11.17 mm/dec` sig), alongside Appalachian snowpack loss (`VA` `SNODP year` clarity `0.889`, `WV` `0.810`) and dense century-long NOAA GHCN/GSOM stations.
2. **Box 2 — American Southwest (`31.25, -120.0, 41.25, -103.0` → `2,829` cells at `0.25°`):**
   - Covers the **top 4 states in the US for summer (`JJA`) and annual (`year`) warming rate and clarity**, every one at **`1.000` clarity (`100%` of cells FDR-significant)**: `NV` (`n=89`, `JJA +0.614 °C/dec` #1 in US, `year +0.477 °C/dec` #2 in US), `UT` (`n=71`, `JJA +0.558 °C/dec` #2 in US, `year +0.455 °C/dec` #4 in US), `NM` (`n=96`, `JJA +0.542 °C/dec` #3 in US, `year +0.483 °C/dec` #1 in US, overall #7 at `0.972`), and `AZ` (`n=97`, `JJA +0.509 °C/dec` #4 in US, `year +0.465 °C/dec` #3 in US, overall #11 at `0.907`), plus `CO` (`n=95`, `JJA 0.990`, `year 0.990`).
   - Simultaneously captures the **#1, #2, and #3 clearest annual drying (`PRECTOTCORR year`) states in the US**: `NM` (`clarity = 0.583`, `-32.19 mm/dec` sig), `UT` (`clarity = 0.521`, `-28.92 mm/dec` sig), and `AZ` (`clarity = 0.361`, `-36.40 mm/dec` sig), plus `NM` winter drying (`DJF clarity = 0.375`, #1 in US) and snow decline (`NM` `SNODP year` clarity `0.458`, `UT` `0.338`, `NV` `0.326`).
3. **Box 3 — Southeast & Southern Appalachians (`30.5, -90.5, 39.5, -75.5` → `2,257` cells at `0.25°`):**
   - Captures a striking **seasonal and multi-variable contrast**: `100%` FDR-significant winter (`DJF`) and annual (`year`) warming across `SC` (`DJF 1.000`, `+0.645 °C/dec` #3 in US), `VA` (`DJF 1.000`, `+0.609 °C/dec` #4 in US), `TN` (`DJF 1.000`, `+0.574 °C/dec` #6 in US), `WV` (`DJF 1.000`, `+0.535 °C/dec`), `MS` (`DJF 1.000`, `+0.493 °C/dec`), `AL` (`DJF 0.978`, `+0.551 °C/dec`), `GA` (`DJF 0.978`, `+0.571 °C/dec`), and `NC` (`DJF 0.891`, `+0.627 °C/dec`), paired with the **Summer Warming Hole null examples** in the exact same states (`KY` `JJA` `T2M` clarity `0.000`, `TN` `0.024`, `MS` `0.147`, `GA` `0.174`, `SC` `0.200`).
   - Also holds the **#1–#8 clearest snow-depth (`SNODP`) declines in the US** (`GA` `0.848` DJF / `0.913` year, `SC` `0.800` DJF, `NC` `0.609` DJF, `AL` `0.556` DJF, `TN` `0.476` DJF, `KY` `0.375` DJF / `0.750` year, `VA` `0.889` year, `WV` `0.810` year) and `KY` annual wetting (`PRECTOTCORR year` clarity `0.344`, `+30.78 mm/dec`).
   - *(Optional Pacific Northwest alternative for summer drying: `42.0, -124.5, 49.0, -111.0` covering `OR, WA, ID`, `7.0° × 13.5° = 29 × 55 = 1,595` cells, where `OR` is #1 in `PRECTOTCORR JJA` drying at `0.538` clarity and `WA` is #2 at `0.348`.)*

---

## 5. Caveats

1. **State assignment by cell centre (`0.5° × 0.625°` resolution):** NASA POWER monthly regional data are on the MERRA-2 `0.5°` latitude by `0.625°` longitude grid (`~55 km × 50 km` at mid-latitudes). Assigning each cell to a state by its centre point works well for medium/large states (`6` to `915` cells) but under-samples narrow coastal states (`DE` has `3` cells and `RI` has `1` cell, both dropped by the `< 4` cell rule; `DC` has `0` cell centres).
2. **Reanalysis vs in-situ stations:** `T2M`, `PRECTOTCORR`, and `SNODP` come from NASA POWER (MERRA-2 reanalysis / gauge-corrected precipitation / modelled land-surface snow depth), not single thermometer or snow-stake stations. Spatial fields are smoother than point station records, and modelled `SNODP` along the southern rain–snow boundary (`GA, SC, NC, AL`) reflects small absolute snow depths (`< 2 cm` seasonal mean) where the disappearance of episodic 1980s/1990s snow events yields high rank-test significance.
3. **Multiple-testing family definition:** Benjamini–Hochberg FDR (`q = 0.05`) is applied across all `m = 3,545` US-assigned land cells as a single nationwide family per `(parameter, season)`. Defining the family per-state (`47` separate small families) or across all `7,765` bounding-box cells (which include `4,220` ocean, Canadian, and Mexican cells) shifts borderline `q`-values near `0.05`.
4. **Autocorrelation-corrected Mann–Kendall estimator:** Per-cell slopes and `p`-values now use `build_grid_trends.cell_trend` → `app.stats.trend.analyze_trend` (`backend/app/stats/trend.py`, matching the live single-point verdict engine and the Ukraine trend map): Sen's median pairwise slope (`×10` per decade) and Mann–Kendall on Sen-detrended ranks (zero-padded onto an integer-year grid across missing years) with variance inflation `ess >= 1.0` taking the maximum of the thresholded Hamed–Rao rank-ACF sum (`|rho_k| > 1.96/sqrt(n)`) and a geometric AR(1) floor driven by the Marriott–Pope bias-corrected lag-1 correlation (cells with `< 15` valid years yield `NaN`). *(The snapshot tables above were generated before `cell_trend` moved from the earlier `pymannkendall` estimator to `analyze_trend`.)*

---

## 6. Data Sources and Licences

- **Climate Reanalysis Grids:** NASA Prediction Of Worldwide Energy Resources (POWER) Project, Regional Monthly API (`https://power.larc.nasa.gov/api/temporal/monthly/regional`), MERRA-2 (`T2M`, `PRECTOTCORR`, `SNODP`), 1981–2025. **Licence:** U.S. Government Public Domain (17 U.S.C. § 105; NASA Open Data Policy, attribution to NASA LaRC POWER Project).
- **US State Boundaries GeoJSON:** U.S. Census Bureau Cartographic Boundary Files, `cb_2018_us_state_20m` (1:20,000,000 scale), fetched as GeoJSON from `https://raw.githubusercontent.com/loganpowell/census-geojson/master/GeoJSON/20m/2018/state.json`. **Licence:** U.S. Government Public Domain (17 U.S.C. § 105; U.S. Census Bureau TIGER/Cartographic Boundary data).
