# Earth Verdict frontend

Implementation of [issue #3](https://github.com/tByte97/Earth-Verdict-Overflowers/issues/3):
a verdict card with editable case parameters, manual checks and progressive disclosure.
React + TypeScript + Vite. UI language is English, as required by the project specification.
No globe, chat, forecast or frontend statistical engine is introduced in this task.

## Run

Node.js 20.19+ (or a supported newer LTS) and pnpm are required.

```sh
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

Open the Local URL printed by Vite (normally `http://127.0.0.1:5173`).
`pnpm build` checks TypeScript and produces `dist/`; `pnpm preview` serves that build.
The committed pnpm configuration allows only esbuild's dependency build script.

## Demo and live integration

The default is **Demo · synthetic data**. Seven saved JSON responses cover every verdict,
all witness statuses and every `not_proven` reason. Select a response, inspect the card,
or press **Check claim** to replay the same response without chat. No statistics are
calculated in the browser. These samples are UI fixtures, not internally recomputed
scientific datasets or actual NASA/NOAA findings. The sample observations are intentionally
sparse and must not be used to reproduce their placeholder statistical outputs.

Changing a parameter clears the previous result. A demo request whose parameters differ
from the selected fixture reports that no response exists; it does not relabel old numbers
as a new calculation. Claim text must also match the fixture. Use live mode for custom cases.

**Connect backend** opens `?source=live`. All requests go through `src/api.ts`:

| Endpoint | Expected JSON |
|---|---|
| `GET /api/variables` | Array of `Variable` objects |
| `GET /api/places?q=…` | Array of places with `place_id`, `name`, `lat`, `lon` |
| `POST /api/check` | `CaseSpec` request → `CheckResult` response |

Vite proxies `/api` to `http://127.0.0.1:8000`. Production hosting must route `/api`
to the backend too. Errors accept the specified `{ "error": { "code": "…", "message": "…" } }`
shape. Requests time out, and editing parameters cancels pending checks. Live errors never
fall back to synthetic results. Required result structure is checked before rendering.

Backend response fields determine the verdict and metrics. Local reason labels are static
translations of `reason`, not generated explanations or a second verdict calculation.
The structured case fields define the check; the free-text claim does not automatically
change them. A new backend result is always displayed with its own returned case parameters.

## Contract dependencies to resolve with the backend owner

The baseline contract is in `docs/08-tz.md` on the repository's `docs` branch.
There was no backend or shared mock in `main` when this implementation started.
`src/types.ts` models that documented shape without changing a backend implementation.

- **r₁ is absent from the documented JSON.** The UI accepts optional `mk.r1`, used only
  in synthetic fixtures for now. Missing r₁ is shown as “Not supplied”. Confirm its final
  path and whether it describes observations or residuals with the backend owner.
- **CI units are ambiguous.** Main `sen.ci_low/high` and witness intervals use different
  scales in the specification example. An optional proposed `presentation.ci_units`
  object explicitly declares `sen` and `witness` units in the fixtures. The UI never
  infers or rescales these intervals when metadata is missing.
- **Anomaly baseline has no documented field.** Optional proposed
  `presentation.baseline` is displayed if supplied. Otherwise details say it is not
  supplied; no anomaly is derived or assumed. The trend fitting period is always visible.
- **Per-field provenance links are not defined.** Both provider records are shown in the
  synthetic fixtures and accessible in one click. An exact primary/witness mapping needs
  backend metadata before live traceability can be fully accepted. Fixture source links
  identify providers and explicitly do not validate the synthetic values.

These are optional frontend expectations to agree on, not an approved change to the shared
API. Completing live-data acceptance depends on the backend providing those metadata.

## Review against the presentation rule (issue #1)

| Requirement | Evidence in this implementation |
|---|---|
| Clear first look | Status with text, colour and symbol; one reason sentence; signed Sen slope with units and fitting period; station agreement badge |
| Every number retained | `How we checked this` → exact-value table recursively includes all numeric and null response fields; full original JSON also available |
| Technical detail | Method comparison, p, CI, optional r₁, correction, every robustness window, k/n, additional-years estimate; complete witness and observation values in exact-value table |
| Units and periods | Numeric field context column; per-window periods; explicit missing-metadata labels; no invented baseline or CI scale |
| Not proven caveat | Visible immediately beside every `not_proven` verdict, with reason-specific wording |
| Provenance | Direct `Data sources` button plus separate disclosure; unsafe URL schemes cannot be opened |
| Manual operation | Editable place, variable, season/month, years, direction and claim; check button without chat |
| Past versus future | Card explicitly labelled `Past observations · Verdict`; no future/scenario UI in this issue; footer says it is not a forecast |

Numeric field inventory:

| JSON fields | Where | Units / period |
|---|---|---|
| `sen.slope_per_decade` | Headline + exact-value table | Variable units / decade; returned case period and season |
| `sen.*`, `mk.*`, `ols.*` | Methods/statistics + exact-value table | Annual/decadal scale as named; dimensionless test statistics; CI scale only if supplied |
| `robustness[*].*`, `robustness_summary.*` | Window table + exact-value table | Each window's years, units / decade, dimensionless p, window counts |
| `series[*].*`, `witness.series[*].*` | Exact-value table | Calendar year and variable units |
| `witness.station.*`, `witness.sen.*`, `witness.mk.*` | Exact-value table + source disclosure | Degrees, km, units / decade, explicit CI metadata, dimensionless p |
| `case.*`, `years_to_wait`, any additional numeric field | Exact-value table | Calendar years/month, coordinates, additional years; unknown metadata explicitly marked |

## Verification

```sh
pnpm build
pnpm test:e2e
```

Browser tests default to installed Microsoft Edge. Alternatively set `BROWSER_EXECUTABLE`
to an absolute Chromium/Chrome path. Set `TEST_BASE_URL` if Vite uses another port.
Start `pnpm dev` in another terminal before tests. The tests run headlessly and use
intercepted API responses for live integration checks; they do not require a running backend.

Six browser tests cover all fixtures, exact numeric-field preservation, manual requests,
invalid demo parameters, missing metadata, backend errors, cancellation of stale responses,
tutorial interaction and desktop/mobile overflow. They save review screenshots in
`test-results/` (gitignored). TypeScript and production build were also checked.

Manual visual review: desktop, mobile, and expanded `not_proven` details.
This is not a timed usability study with pupils; the five-second reading goal still needs
validation with the intended audience. API tests use mocks rather than real climate services.

Implementation references: `docs/prototypes/scenario-prototype.html` (`.side`),
`docs/08-tz.md` (F2–F4), and the presentation rule in issue #1, all on `docs` or its task branch.
