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
  Implementing interactive scenario charts remains in issue #7.

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
Google Fonts use HTML preconnect links and `display=swap`, with system-font fallbacks;
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


## Globe-left workspace

The user subsequently requested integration of the contributor's `feat/globe-case-station`
branch. The desktop workspace now uses a 3:2 grid: globe on the left (approximately 60%),
and one stacked investigation panel on the right (approximately 40%). Tablets/phones stack
the map above the panel without horizontal overflow.

The saved-case selector remains visible. Saved cases initially collapse **Edit parameters**
so the verdict stays in view; live/new checks open the form automatically. A successful
check collapses the parameters and shows the result. The globe is sticky while the panel
is explored, and loads separately from the core form/card bundle.

The contributor's MapLibre globe keeps point/station markers and NASA GIBS Blue Marble
imagery. **Globe view** shows planetary context; **Local view** zooms to the selected place.
Clicking a point updates the case coordinates and clears the old result. Unsupported
browsers get a map-only fallback while the form and evidence remain usable. External
imagery still depends on NASA GIBS availability.

### Globe notes

- Picking a point (map click or the keyboard-accessible "Use map centre" button) rounds coordinates to two decimals and builds the place in `src/globe/place.ts`: id `pt:{lat},{lon}` (for example `pt:50.45,30.52`) and name `50.45° N, 30.52° E`. The backend normalises the point to its POWER grid cell. Picking fills the form; the check runs only on **Check claim**.
- Blue Marble tiles are fetched from NASA GIBS at runtime. If they are unreachable the globe falls back to a plain background and markers still work. For a fully offline demo, self-host the tiles and change `BLUE_MARBLE` in `src/globe/Globe.tsx`.
