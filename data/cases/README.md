# Saved backend cases

These files are `CheckResult` responses shared by the API and frontend. Observations are real NASA/NOAA data. Statistics use `backend.app.stats v2`; `meta.stub: true` still marks the supplied snapshots as provisional, not wholly synthetic data. Use the metadata of each response instead of inferring its origin from the file name.

| File | Current verdict | Additional waiting at the observed rate |
|---|---|---|
| `kyiv-summer-heat.json` | `confirmed` | Not applicable (`null`) |
| `mock.json` | Alias of the Kyiv heat case | Not applicable (`null`) |
| `lviv-drier.json` | `not_proven` | 15 years |
| `kyiv-winter-snow.json` | `not_proven` | 106 years; DJF starts in 1982 |
| `kyiv-colder.json` | `refuted` | Not applicable (`null`) |
| `kyiv-summer-rain.json` | `refuted` | Not applicable (`null`) |
| `global-warming-stopped.json` | `refuted` | Not applicable (`null`) |

## Contract and provenance

`backend/app/models.py` is the contract. The frontend validates it with Zod before rendering. Contract changes require a coordinated PR.

- `series`: one value per calendar year. A missing value stays `null`; do not replace it with zero or compress the time axis.
- `sen`, `mk`, `ols`, `robustness`: backend statistics, not raw provider measurements. Sen confidence limits are per decade. Historical analysis periods are not anomaly reference baselines.
- `witness`: the independent station check, or `null` if no suitable station exists. Keep coverage, gaps and optional rate-comparison information.
- `steps`: the eight processing explanations.
- `provenance`: provider/product, request URL, retrieval date and license. Derived quantities also need their corresponding backend method record in the UI.
- `extrapolation`: conditional continuation of the trend, separate from the historical verdict.
- `scenarios`: conditional model paths with their own anomaly baseline. The Kyiv heat case now uses real NASA NEX-GDDP-CMIP6 ensemble output (`synthetic: false`); read the flag and source from each response. Missing scenarios remain `null`.

## Detection duration: issue #6

`detection.multipliers` contains rate factors (currently x0.5, x0.75, x1, x1.5, x2). `years_needed` is the **total** number of observed years needed for the production trend test to detect the assumed rate in at least 80% of seeded AR(1) simulations. `n_years` is the number already observed.

`years_to_wait` is the **additional** waiting estimate at x1 when applicable. Both use the same power-simulation engine in `backend/app/stats/wait.py`; the earlier Weatherhead formula is not the current product calculation. A null estimate is not zero, a forecast or a guarantee of detection. Source disagreement has no waiting estimate.

The existing presentation interpolation is allowed only between adjacent non-missing detection nodes in log-rate/log-duration coordinates. Keep exact nodes exact and label interpolated values. Do not interpolate p-values or bridge missing duration nodes.

## Observed prefix history: issue #6 contract addition

`detection_history` is optional/nullable for older responses. Newly generated responses and these seven snapshots include:

- `method: "sen_mann_kendall"`, `alpha: 0.05`, `min_observations: 15`, and a fixed `start_year`;
- one `points` entry for every calendar year through the case's end year;
- each point's `end_year`, `n_observations`, exact `p`, applied `correction`, and `status` (`ok` or `short_series`).

Each point uses only the primary annual observations available through its end year, with the same Sen / autocorrelation-corrected Mann-Kendall implementation as the production trend. Input aggregates are unrounded, as for the main calculation. Published annual observations are rounded for display. Prefix p-values retain backend precision; the main `mk.p` is rounded to three significant digits. Consequently, compare the final prefix after that same formatting, rather than expecting bitwise equality with the displayed main value.

Before 15 valid observations, `p` and `correction` are null and the status is `short_series`. Counts exclude missing observations; calendar years are retained. No new claim verdict is attached to a prefix. p-values can rise or fall, and a threshold crossing alone does not satisfy the full robustness/station decision.

The slider selects supplied points locally. It cannot change `case`, the historical verdict, the original waiting estimate or the separate rate experiment. If history is absent, show an unavailable explanation instead of manufacturing values.

This is a coordinated schema addition: the updated client accepts older responses, but older clients with strict unknown-field validation must be updated before consuming the new payload. Update the Python model and frontend schema together.

## Rebuild

After installing the backend dependencies and fetching the source data, `python tools/build_cases.py` uses `app.check.assemble_result` to generate both current statistics and prefix histories. Live `/api/check` uses that same assembly path. No new endpoint, browser-side statistical library or calculation on slider movement is required.

Regenerate the complete saved responses with that builder after contract updates; do not merge or append JSON fields by hand. The rebuilt responses include `detection_history` together with the Sen pivot/band, baseline, structured steps and expanded scenario metadata. Retrieval/generation metadata may change during a rebuild. The formatted final prefix p-value must still agree with the response's main `mk.p`.
