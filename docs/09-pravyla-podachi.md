# 09 · Presentation rule: simplify without losing data

Required review guidance for the visualization team. Applies to every new or changed
screen before merging into `main`: globe, verdict card, charts, scenarios and any
implemented demo, chat or exported-result surface.

Task: [issue #1](https://github.com/tByte97/Earth-Verdict-Overflowers/issues/1).
This task establishes the review workflow. Individual screen implementation belongs
to the corresponding visualization issues.

## Information hierarchy

| Level | Required content |
|---|---|
| Immediately visible | Claim, place, variable, season, analysis period, verdict, principal rate/value with units and time scale, and the not-proven caveat when applicable |
| Expandable details | Every secondary calculation, exact received precision, uncertainty, methods, robustness windows, witness fields and limitations |
| One-click provenance | The relevant provider or method record, input sources, product/version when supplied, request/data URL, retrieval date and license |

The source action next to a value opens its relevant provenance or method record in one
click, without requiring the user to open a different disclosure first. Disclosures must
also work with a keyboard and expose their expanded/collapsed state.

## Required checks

### 1. Preserve every calculation

- Map every numeric field in `CheckResult` to the main view, an expandable block or an
  accessible exact-value table. Include nested objects and arrays: observations, station
  coordinates/distances, witness comparisons, uncertainty, methods and every robustness window.
- Readable rounding is allowed only when full received precision remains accessible.
  A small nonzero p-value must not be rounded into an apparent zero.
- Null or absent values are not zero. Explain their actual meaning: missing observations,
  an undetermined waiting estimate or a quantity that does not apply to the verdict.
- Do not silently drop unsupported metadata. Record a blocker for the relevant backend
  or screen task rather than inventing values or claiming that the check passed.

### 2. Keep units and periods with values

- A trend rate needs both variable units and time scale (for example, °C / decade), plus
  its fitted years and season. An anomaly also needs its actual reference baseline.
- The fitted analysis period and anomaly baseline are different. Absolute observations
  do not acquire a made-up anomaly baseline; mark it not applicable with a reason.
- Axes, tooltips and tables keep their units and time context. Shared visible table
  headers may supply that context. p, tau, z, R², autocorrelation and ratios are dimensionless;
  counts identify years, observations or windows as appropriate.
- Read confidence-interval units from the current backend contract. Do not infer the
  scale from a nearby slope field or a historical example in the specification.

### 3. Trace observations and derived results honestly

- Check the path from UI value to JSON field to the appropriate provenance/method record.
  A provider homepage alone is not evidence for a particular calculation.
- Observations identify their actual provider/product. Derived statistics identify the
  backend method and input observations. Detection simulations, trend extrapolations and
  scenario curves must not masquerade as raw NASA/NOAA measurements.
- Use explicit field roles or unambiguous supported metadata for source mapping. Never
  guess the role from translated/free-text `what` descriptions or select the first provider.
  Missing or ambiguous mappings remain explicit blockers for the affected surface.
- Keep metadata distinctions: real observations may have provisional statistics
  (`meta.stub`); wholly synthetic examples and stylised scenarios are labelled synthetic.
  A saved JSON file is not automatically a synthetic dataset.

### 4. Explain Not proven correctly

For every implemented surface that shows `not_proven`, display this meaning next to the
verdict, not only inside a tooltip, tutorial or technical disclosure:

> There is not enough evidence to establish a trend against the background of variability.
> This does not mean there is no change.

Add the actual `reason`: insufficient significance, a short record, disagreement between
sources or sensitivity to selected years. A test not performed due to a short record must
not be described as a completed non-significant test. Never replace this verdict with
“No change”, “Trend absent” or “Everything is stable”.

Additional waiting is a conditional backend estimate, not a guaranteed detection date.
Distinguish total required duration, years already observed and additional years. Null
waiting is not zero and does not establish a trend. A hypothetical speed control cannot
change the historical verdict or its backend waiting estimate.

### 5. Separate past evidence from future illustrations

- Use separate labelled sections or tabs for **Past observations · Verdict** and future
  conditional estimates. Structure, labels and line styles carry the distinction; color
  alone is insufficient.
- If both appear on one chart, show the boundary between their periods, a legend and
  tooltips identifying the kind of each point.
- Label extrapolation as an illustration, model scenarios with their model/SSP and source,
  and synthetic experiments as synthetic. Stylised placeholder curves are not CMIP6 outputs.
- Show supplied assumptions, horizon, units, scenario baseline and uncertainty. Changing
  a future scenario must not change or relabel the historical verdict.

### 6. Respect the backend contract

All statistical values and the verdict come from validated backend JSON. LLM text cannot
supply or override rates, p-values, coordinates, years, verdicts or reasons. Deterministic
UI wording may explain the returned enum/reason without inventing scientific conclusions.

UI formatting and explicitly approved presentation interpolation may use supplied values.
For example, the current detection contract permits labelled log-rate/log-duration
interpolation between adjacent valid simulation nodes. This is an illustration, not a new
statistical calculation. Exact nodes stay exact; missing nodes are not bridged or made zero.

The source of truth for current fields and units is the
[backend model](https://github.com/tByte97/Earth-Verdict-Overflowers/blob/main/backend/app/models.py).
Use its typed `detection`, `extrapolation` and `scenarios` sections without treating future
illustrations as observed evidence. Contract changes require the coordination specified in
section 3 of the technical specification.

## Review workflow before merging a screen

1. **Author:** list every affected screen/surface and identify the JSON response or fixture.
2. **Author:** inventory every numeric field, including nested fields/arrays, using the
   report below. Open all disclosures/tables and verify exact values, units, analysis
   period, baseline where applicable and provenance/method access.
3. **Author:** check applicable confirmed/refuted/not-proven states and reasons; witness
   absence/disagreement; gaps, genuine zero, small nonzero p and null estimates. Exercise
   place/period changes to exclude stale labels or provenance. Test fixtures are identified.
4. **Author:** attach evidence for the default view, open details, not-proven caveat and
   past/future separation. State limitations. Mark a non-applicable check with its reason;
   do not mark an unperformed check as passed.
5. **Reviewer:** independently verify each affected screen and its report. The specification
   identifies Maksym as reviewer. Resolve missing values/context, misleading verdicts,
   provenance gaps and mixed historical/future presentation before accepting the screen.

| Screen/surface | JSON field(s) | Exact-value location | Units | Analysis period / baseline | Provenance or method | Result / evidence |
|---|---|---|---|---|---|---|
| Fill in | e.g. `sen.slope_per_decade` | Main card and details | From contract | From response; baseline or justified N/A | Specific record | pass / blocker / justified N/A |

An array may be recorded as `series[*].value` only when the whole array is accessible and
checked consistently. Include both original values and relevant UI formatting in evidence.
The report is completed for each screen-changing PR; a blanket checkbox is not evidence.

## Adoption and task boundaries

- This guide is linked from the documentation index and section 2 of the specification.
- `.github/pull_request_template.md` belongs in default branch `main` so GitHub can insert
  the review checklist automatically. The companion workflow PR adds that file; until it
  merges, authors copy its checklist manually. Full documentation stays on branch `docs`
  as required by the specification's Git section.
- This is manual review guidance, not a claim that CI checks visual honesty or that branch
  protection has been configured. No new deployment, screen implementation or statistical
  engine is required by issue #1.
- Existing implementation evidence is recorded in merged
  [PR #16](https://github.com/tByte97/Earth-Verdict-Overflowers/pull/16) and its frontend
  review notes. That evidence does not certify screens added or changed afterward.
- Keep issue #1 open until the guide and workflow activation have been reviewed/integrated.
  Each future screen still requires its own actual presentation review.

## Specification references

- [Development vectors](05-vektory-rozvytku.md): vectors 1 and 14.
- [Architecture](07-arkhitektura-i-rozrobka.md): the four core principles.
- [Technical specification](08-tz.md): sections 2, 3 and 6.
- [Scenario prototype](prototypes/scenario-prototype.html): sidebar and explanatory notes;
  an interaction reference on synthetic data, not production acceptance evidence.
