## Change

Explain the problem, resulting behaviour and linked issue(s).

## Validation

State what was checked, the data/fixture used, the results and remaining limitations.

## Presentation review · issue #1

Apply this checklist to every new or changed screen before merge to `main`.
For a PR without screen changes, write **Not applicable** with a reason below.
Do not check an unperformed review or claim that a missing screen was verified.

Detailed guidance: [Simplify without losing data](https://github.com/tByte97/Earth-Verdict-Overflowers/blob/82e911fcca03c94c64acf395f3eeef13d14e60b4/docs/09-pravyla-podachi.md).
The guide is version-pinned so it is readable before the documentation PR is merged.

- [ ] Every affected screen/surface is listed in the report below.
- [ ] Every calculation number remains accessible in the main view, a disclosure or an exact-value table; received precision and null/zero distinctions are preserved.
- [ ] Units and analysis period accompany values; anomalies also show their actual baseline. Dimensionless statistics and justified baseline N/A are labelled.
- [ ] Each number's relevant provenance/method record opens in one click. Derived statistics, detection, extrapolation and scenarios are distinguished from raw provider observations and identify their inputs.
- [ ] All statistical numbers and the verdict come from backend JSON, not LLM-generated text. Real observations, provisional statistics and synthetic/stylised data are labelled accurately.
- [ ] Every applicable `not_proven` state visibly explains that evidence is insufficient against variability and that this does not mean no change; the explanation matches `reason`.
- [ ] Historical evidence/verdict and future conditional estimates are visually separated and labelled. Hypothetical controls cannot alter the historical verdict. Approved presentation interpolation is labelled and does not bridge missing nodes.
- [ ] Applicable verdict/reason/witness states, missing observations/estimates, genuine zero, small p and place/period changes were checked; stale data/context are excluded.

### Per-screen evidence

JSON response or fixture path:

| Screen/surface | JSON field(s) | Exact-value location | Units | Analysis period / baseline | Provenance or method | Result / evidence |
|---|---|---|---|---|---|---|
| | | | | | | |

Attach evidence for the default state, open details, the not-proven caveat and
past/future separation. Arrays may be grouped only when the whole array is accessible
and checked consistently. Explain every non-applicable item and disclose blockers.

Not-applicable items and reasons / limitations:

### Reviewer confirmation

Reviewer: Maksym, as identified in the technical specification.
The reviewer completes this after independently checking the affected screens and report.

- [ ] Each affected screen has been verified and no presentation blockers remain.
