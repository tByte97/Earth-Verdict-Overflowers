# Earth Verdict · verdict card

Implementation of issue #3 using the shared backend models and snapshots from `main`.
React + TypeScript + Vite. UI language: English, as required by the project specification.

## Run locally

Node.js 20.19+ (or a supported newer LTS) and pnpm:

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
in-flight request. The response shape is checked before rendering.

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
| Source mapping | Primary observations/statistics → primary source; `witness.*` → station; `scenarios.*` → future-scenario record |
| Manual check without chat | Editable form and `Check claim` |
| Brief tutorial | `How to use` |

Reason text is a deterministic label for the returned `reason`; it does not generate
numbers or independently decide the verdict. Unsafe source URL schemes are not opened.

## Verification

```sh
pnpm build
pnpm test:e2e
```

Start `pnpm dev` in another terminal before browser tests. They use installed Microsoft
Edge by default; set `BROWSER_EXECUTABLE` for another Chromium executable and
`TEST_BASE_URL` for another server URL. Screenshots are saved to gitignored `test-results/`.

Eleven browser tests cover the three canonical snapshots, all number preservation,
manual form submission, API error/cancellation behaviour, unit/CI/r1 alignment, witness
null gaps, source access, historical/future separation, tutorial interaction and layout
on desktop/mobile. Additional verdict reasons and witness agreement states use intercepted
test-only synthetic responses; these fixtures are not shipped to users.

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

No changes to `main.tsx` or the globe layout were made for this follow-up. The colleague
working on #2 owns the globe-left / form-and-card-right integration.
