# Earth Verdict · verdict card

Implementation of issue #3 using the shared backend models and snapshots from `main`.
React + TypeScript + Vite. UI language: English, as required by the project specification.

## Run locally

Node.js 20.19+ (or a supported newer LTS) and pnpm 10 (pnpm 9 also supports the build-script allowlist):

```sh
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

Open the Local URL printed by Vite, normally http://127.0.0.1:5173.
`pnpm build` type-checks the application and creates `dist/`.

## Shared JSON snapshots

`src/data.ts` imports the canonical JSON files directly, without rewriting their values:

| File | Case | Verdict |
|---|---|---|
| `data/cases/kyiv-summer-heat.json` | Summers in Kyiv are getting hotter | confirmed |
| `data/cases/lviv-drier.json` | Lviv is getting drier | not_proven |
| `data/cases/kyiv-winter-snow.json` | Kyiv winters have more snow | not_proven |

The observations are real according to the team's data README. The statistics are
provisional (`meta.stub: true`), and future curves are stylised when `scenarios.synthetic`
is true. These distinctions are visible in the UI; the application does not call all
shared data synthetic or present provisional statistics as final findings.

The case selector fills the editable parameters. **Check claim** retrieves the exact matching
saved response without chat. Unsupported combinations produce a clear message; no new
statistical calculation or verdict is made in the browser. Old results disappear when
parameters change. The previous synthetic fixtures are now test-only and excluded from
the production import graph.

## API integration

All data access goes through `src/api.ts`. The default published mode uses the shared
snapshots and does not require a calculation server. Developers can explicitly open
`?source=live` when an API server is available:

| Endpoint | Contract |
|---|---|
| `GET /api/variables` | Array of variable objects |
| `GET /api/places?q=…` | Array of places |
| `POST /api/check` | `CaseSpec` → `CheckResult` |

Vite proxies `/api` to `http://127.0.0.1:8000`; a production API installation needs its own
route. Calculation endpoints are not implemented by this frontend issue. Network errors
never fall back to saved results. Requests time out, and editing parameters aborts an
in-flight request. The complete response shape is validated by Zod before rendering, including nested arrays and optional witness-rate comparisons. TypeScript types are inferred from the same schemas; there is no case-data cast. A React error boundary provides recovery if rendering still fails.

## Contract alignment

The source of truth is `backend/app/models.py` and `data/cases/README.md` in this checkout.
No optional `presentation` extension is invented or required.

- Both main and witness Sen confidence intervals are **per decade**, as documented.
- Residual lag-one autocorrelation comes from **`detection.phi`**, including a valid zero.
  It is labelled as residual autocorrelation bounded to 0–0.9 for the detection estimate;
  it is not substituted for raw-series autocorrelation. A response lacking the field shows
  “Not supplied”.
- Historical series and slopes are absolute, with the fitting years and season shown.
  No anomaly baseline is invented for them. Future scenario anomalies use the supplied
  **`scenarios.baseline_period`** and **`baseline_value`** in their separate disclosure.
- `witness.coverage`, `method_note`, every observation (including nulls), `steps`,
  `detection`, `extrapolation`, `scenarios` and `meta` remain available in the original JSON.
  Every numeric/null leaf also appears with full received precision in a context table.
- Future numbers have their own visually distinct disclosure and cannot alter the verdict.
  The scenario paths are drawn on the record chart (see below).

## Presentation review (issue #1)

| Requirement | Where to verify |
|---|---|
| Three statuses, one reason, one main metric, witness badge | Main card |
| Clear not-proven caveat | Always visible next to any `not_proven` status |
| p, CI, r1, OLS, k/n | `How we checked this` |
| All numbers and null values | Exact-value tables; full original JSON |
| Units and fitting period | Metric, method table, exact-value context columns |
| Scenario baseline and future distinction | `Future illustrations · separate from the verdict` |
| One-click provenance | Main `Data sources` button and source buttons on numeric rows |
| Source mapping | Measured series/station fields → unambiguous recognised provider URLs; derived statistics, detection, extrapolation and scenarios → explicit method records. No matching on free-text `what`. |
| Manual check without chat | Editable form and `Check claim` |
| Brief tutorial | `How to use` |

Reason text is a deterministic label for the returned `reason`; it does not generate
numbers or independently decide the verdict. Unsafe source URL schemes are not opened.

## Verification

```sh
pnpm build
pnpm test:e2e
```

Install the test browser once, then run the suite:

```sh
pnpm test:install
pnpm test:e2e
```

Playwright Test starts and stops its own Vite web server on port 4173 and uses its bundled
Chromium. No running development server or installed Edge is required. `BROWSER_EXECUTABLE`
is an optional override for debugging; `TEST_BASE_URL` opts into an explicitly managed
external server. The normal path needs neither. Screenshots go to gitignored `test-results/`.

The reviewed build configuration uses `pnpm.onlyBuiltDependencies: ["esbuild"]` in
`package.json` instead of a frontend workspace root. Vite explicitly allows this repository
root so canonical `../../data/cases` imports work independently of workspace detection.
Google Fonts (Cormorant Garamond, IBM Plex Sans, IBM Plex Mono) use HTML preconnect links and `display=swap`, with system-font fallbacks;
there is no stylesheet `@import` chain.

Browser tests cover canonical snapshots, numeric preservation, manual requests, errors
and cancellation, missing estimates and interpolation, units/r1, station gaps, provenance,
past/future separation, tutorial interaction, responsive layout and the review regressions:
a backend-only variable catalogue, empty catalogues, malformed nested JSON, nullable source
versions, optional witness rates, error-boundary recovery, unknown city aliases, null caveats,
missing-station wording and distinct accessibility announcements.

The five-second reading goal has been checked visually, not through a timed pupil study.
The deployed app uses saved shared responses; arbitrary periods need the calculation API.


## Consistent detection and waiting estimates (PR #17)

This branch includes `fix/detection-consistency` from PR #17 so the demo uses one
backend simulation engine for both `detection.years_needed` and `years_to_wait`.
PR #17 remains separately reviewable; nothing has been merged into `main` by this task.

`How we checked this` includes a reusable `DetectionEstimate` control:

- **Total observation duration needed** comes from `detection.years_needed`.
- **Observations already available** comes from `detection.n_years`.
- **Additional waiting at observed rate** comes directly from `years_to_wait`, without
  a separate frontend waiting formula. For a resolved claim it is not applicable.
- `null` for an unproven claim reads **Not determined**, with an explanation. It never
  becomes zero or a claim of detection. If simulated duration was already reached but
  the observed trend is unproven, that limitation is stated explicitly.
- Saved multiplier nodes are shown exactly. Intermediate positions interpolate linearly
  in log-rate / log-duration coordinates per the revised backend contract. They are
  labelled as interpolated illustrations, not fresh statistical calculations.
- Missing endpoints are never bridged, extrapolated or treated as zero. The hypothetical
  rate does not change the historical verdict or backend additional-waiting value.

The canonical v2 snapshots show 60 total / 45 observed / 15 additional years for Lviv,
and 150 total / 44 observed / 106 additional years for winter snow. These are conditional
estimates, not promises. Numbers remain traceable in the exact-value tables and raw JSON.

The detection-consistency follow-up did not alter the globe layout. The later review fixes change only live-form initialization, lifecycle announcements and error-boundary wiring in `main.tsx`. The colleague
working on #2 owns the globe-left / form-and-card-right integration.


## PR review follow-up

All ten points in review `5905235919` are tracked in `REVIEW.md`. Live mode starts with
an empty claim/place and no demo variable; the initial variable is selected from the
validated backend catalogue. Unknown or empty catalogues cannot submit a demo default.

`schema.ts` follows the current `backend/app/models.py` and additionally accepts optional
`Witness.rates` from `feat/witness-rate-check`, plus nullable optional `Provenance.version`.
`witness: null` is the sole no-station representation; `agreement: "no_station"` inside a
witness object is rejected. Invalid payloads produce a contract error, not a blank page.


## Layout and theme

The page follows the Trend Detective layout from issue #41: a dark full-screen page with the
evidence panel fixed on the left (500 px, 440 px at ≤1100 px, scrolls on its own) and the stage
with the globe filling the rest. At ≤900 px the stage becomes a 58vh block above the panel and
the page scrolls; there is no horizontal scroll at 390 px.

- Colours and fonts are tokens on `:root` in `src/styles.css` (Cormorant Garamond for titles,
  IBM Plex Sans for text, IBM Plex Mono for numbers and eyebrows, loaded from Google Fonts with
  system fallbacks).
- The panel header holds the wordmark, the one-line promise (its period comes from the open
  case) and the mode tabs. The footer lists the data and imagery credits.
- Stage chrome: a seeded procedural star field, a vignette that deepens during case flights,
  the projection badge (3D globe / globe → 2D / 2D map · Web Mercator), the stage legend (trend layer and markers) and
  the stage title built from the result (season, period, series provider, variable).
- Pollution events and the CO₂ calculator open in the stage with their own scroll; the globe
  stays mounted (only hidden), so returning to Climate claims does not reload the map. They
  keep the previous light styling through `.legacy-light` until they get the dark theme.

### Globe notes

- Picking a point (map click or the keyboard-accessible "Use map centre" button) rounds coordinates to two decimals and builds the place in `src/globe/place.ts`: id `pt:{lat},{lon}` (for example `pt:50.45,30.52`) and name `50.45° N, 30.52° E`. The backend normalises the point to its POWER grid cell. The picked spot is drawn as a cream ring; the station keeps its own marker.
- Camera: choosing a saved case or a searched place flies there in about 3.7 s (rise to orbit, turn, descend to the local view at zoom 4.75). Dragging the map or a view button interrupts the flight. A picked point leaves the camera where it is. With reduced motion the map jumps without animation. The globe unrolls into a flat map between zoom 3.2 and 4.8.
- Blue Marble tiles are fetched from NASA GIBS at runtime. If they are unreachable the globe falls back to a plain background and markers still work. For a fully offline demo, self-host the tiles and change `BLUE_MARBLE` in `src/globe/Globe.tsx`.


## Trend map (issue #41)

The globe shows the precomputed, FDR-corrected trend layer from `GET /api/grid` (code in `src/globe/`).

- **Data.** Period, units, `q`, the opposite pair and the variable all come from the layer. Variable and season
  buttons come from `GET /api/grid/index`; when the index is missing (404) only the current case's layer is shown.
  Saved mode reads the same precomputed files from `data/layers/`, so the deployed app shows the map without a backend.
- **Rendering.** `paint.ts` paints one smooth image on an `image` source: bilinear blend between cell centres,
  faded next to missing cells and at the data edge, resampled to Web Mercator rows. The blend is colour only.
  Dots mark `significant_fdr` cells; "Fade trends that could be chance" fades the others.
- **Colour scale.** Diverging OKLab ramps per variable. The limit is the 95th percentile of |slope| rounded to a
  nice step: a display scale, not a statistic.
- **Legend and caption.** The caption share is printed only when the layer carries `n_cells` and
  `n_significant_fdr`; the browser never counts cells.
- **Tooltip.** Hovering shows the exact values of the cell under the pointer.
- **Opposite regions.** With `pair`, two chips and a dashed line mark the regions, and the panel callout repeats both
  slopes, p-values, the distance and the basis (FDR or raw p). Without it the callout says there are none.
- **Click to check.** In connected mode a click (not a drag) runs `POST /api/check` for `pt:{lat},{lon}` with the
  layer's variable, season and period, `claim_direction: "change"` and a template claim. A new click cancels the
  previous request; changing the layer re-checks the picked spot. Saved mode explains that this needs the backend.

`tests/trend-map.test.mjs` checks the legend against the API, the tooltip, the pair chips, the click request,
the missing-index fallback and saved mode, and writes `test-results/trend-map-{desktop,mobile}.png`.


## Step pipeline (issue #5)

`src/steps/StepPipeline.tsx` shows the eight backend `steps` (raw → season → yearly → trend →
chance check → robustness → station → verdict) above **How we checked this**, whose method
table, robustness windows, exact values and data sources stay the detailed view.

- Each step shows its `title`, `value` and `detail` exactly as returned. A missing step is
  reported as "Step not supplied by the backend" instead of being skipped.
- Mini visuals draw backend fields only: the raw step's `monthly` record, the season step's
  `months`, a sparkline of `series`, `series` with the `sen.band` fan, the robustness windows,
  and `series` with `witness.series` (gaps stay gaps). Nothing is fitted in the browser.
- Under each step, the paths in its `fields` are shown with their exact values. The chance
  step shows the threshold `alpha` and whether the methods agree (`methods_agree`,
  `methods_reason`); the season step lists `years_dropped` when there are any.
- The raw monthly record (`steps.N.monthly`) is left out of the exact-value table, since the
  raw step's mini chart shows it.
- Each step's source button is chosen by step `id` (NASA POWER, NOAA NCEI or backend
  statistics) and opens the matching record in **Data sources**.
- Mini visuals are small inline SVGs, like the full-size record chart.

`tests/steps.test.mjs` checks order and text against the canonical JSON, the mini visuals,
the source links and a response with a missing step.


## Record chart and evidence timeline (issue #41, sections 4d–4e)

`src/chart/RecordChart.tsx` draws **The record at this spot** as inline SVG, under the station badge:

- `series` as a thin line with dots, Sen's line from `sen.band[].mid` and the 95% fan from `sen.band[].low/high`.
- The station `witness.series` in a second colour. A `null` year breaks the line; it is never bridged or drawn as zero.
- A dashed line at `baseline.mean`, labelled "{baseline.period} average"; the note says whether it is the 1991–2020
  normal or the whole-record average (`baseline.kind`).
- One stripe per year under the chart, diverging around `baseline.mean` with the same OKLab ramps as the trend map
  (`src/chart/ramp.ts`). The colour scale is a display choice only.
- Hover or the arrow keys show the year, the value, the trend-line value and the station value.
- The exact values for every year stay in a table under the chart.
- When the optional `detection_history.emerged_year` is supplied, a dashed vertical line marks it.

The evidence history (`DetectionHistoryChart`) is a block timeline: one block per end year, filled when
`status == ok` and `p < alpha`, with the exact p in each block's title. "Signal emerged" shows `emerged_year`,
or "—" while the backend does not supply it. The end-year slider and the exact-values table are unchanged.

## Future scenarios on the record chart (issue #41, section 4f)

When `scenarios` is present, the record chart's time axis runs on to the last node year (2100), as in the team's
scenarios prototype. Right of a "now" divider at `case.end_year`:

- each path's median is drawn at its node years from `scenarios.paths[].median_value`; the selected path also gets
  its low–high fan from `low_value` / `high_value`. Lines only join nodes; there are no values in between.
- three path buttons show the plain `label` with the SSP code beside it; node buttons (2030 / 2050 / 2070 / 2100)
  are labelled with `windows[i]` ("2050 = average of 2041–2060").
- the analog sentence is worded from `analogs[i]` (`analog_rank` 1 = highest on record); `beyond_record` reads
  "would be beyond anything in the {start}–{end} record".
- the disclaimer, `scenarios.source`, `baseline_period`, `baseline_value` and `note` sit under the controls.
  Choosing a path or node never changes the verdict.
- `scenarios: null` hides the future zone and the controls and shows one line explaining why.

All scenario values also stay in **Future illustrations** with their exact precision.
