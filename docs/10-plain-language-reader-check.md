# Plain-language glossary and reader check (issue #8)

Status: **prepared, not yet tested with readers**. No participant feedback has been collected.
This file is the protocol and a blank record form, not evidence of a completed study.
Issue #8 stays open until 3–5 real readers have completed the check and any confusing copy
has been revised and checked again.

## Copy and integration

All UI explanations are English. The source of truth is
[`frontend/src/method/glossary.ts`](https://github.com/tByte97/Earth-Verdict-Overflowers/blob/feat/plain-language-glossary/frontend/src/method/glossary.ts).
`TermHelp` supplies keyboard/touch explanations beside terms. “Words in this check” lists
all seven definitions, including terms that do not apply to every dataset. The result's
variable definition and caveat are still read from backend JSON. No statistic or verdict
is recalculated by the glossary.

The definitions below are the initial copy, before reader feedback:

| Term | Initial English explanation |
|---|---|
| Trend | A long-term pattern of change, despite ups and downs from year to year. Its rate tells us how fast the values change. |
| Anomaly | How much a value differs from the average for a stated reference period. Always read it together with that reference period. |
| p-value | Under the test’s assumptions, p is the chance of a result this extreme or more extreme if there were no trend. It is not the chance that the claim is false. |
| Confidence interval | A range showing uncertainty in the estimated rate of change, under the method’s assumptions. A wider range means a less precise estimate. |
| Reanalysis | A weather model guided by observations to build a consistent record of past conditions. It is not a thermometer reading at the selected point. |
| Period robustness | We repeat the trend check with slightly different start and end years. If the conclusion changes a lot, it depends too much on the chosen period. |
| Witness station | A nearby weather station provides a second record to compare with the main data source. It may have gaps or be unavailable, and the records can disagree. |

An anomaly needs its stated reference period and is not an error or an unusual event.
Statistical significance does not measure the size or importance of a change.
The existing visible “Not proven does not mean no change” explanation stays beside that verdict.
A confidence interval concerns the estimated trend rate, not the range of weather values
or a guarantee about the future. Its confidence level describes repeated use of the method,
not a probability assigned to this one fixed interval. Preserve those distinctions if copy changes.

Basis: [methodology](04-metodyka-i-statystyka.md), especially the “Для учня” passages and
its updated simulation section; [specification](08-tz.md), M7 and variable definition/caveat;
[explanation pitfalls](05-vektory-rozvytku.md), section 14; [presentation rules](09-pravyla-podachi.md).
Use the current backend contract if an older explanatory example differs from the implementation.

### Coordination with the method panel in #41

The planned sixth PR for #41 has `frontend/src/method/text.ts` for “How the detective decides”.
This glossary does not replace the unfinished panel or copy its files into main.
Once that work is integrated, import `glossary` from `./glossary` in `text.ts` where a definition
is shared. Keep the method narrative in its existing file. Reader-led revisions can then
update the definitions in one place without changing numerical logic or backend step text.

## Preparation

1. Use the glossary branch or the code PR preview. For local use: install frontend dependencies,
   run `pnpm dev` from `frontend`, and open the printed local URL. A phone can use a shared
   prototype/screen, or the facilitator can present the mobile viewport.
2. Recruit **3–5 real readers without technical training**; school pupils and teachers are
   appropriate. Ask permission to write anonymous notes. Use R1–R5, not names/contact details.
3. Record the build commit, device/viewport and UI language for each session. Check that
   the reader can understand the English UI. A language barrier is a finding, not a statistical misunderstanding.
4. Start with “Summers in Kyiv are getting hotter” and keep the Lviv rainfall case ready. These work
   without the calculation API; globe imagery and fonts can still need a connection.
5. Allow about 5–10 minutes per reader. Do not teach the terms before the first interpretation.
   Ask them to think aloud. Separate their own explanation from an interpretation suggested by the facilitator.

## Neutral script

Read: “Please show what you would click and say what you think this screen means. We are
checking the wording and the screen, not testing you. If something is unclear, please say so.”

| Task / neutral question | What to observe, not an answer to read aloud |
|---|---|
| Open the Kyiv summer case. “What is the claim, and what is the conclusion?” | Names the place, summer season and analysis years; understands Confirmed supports the stated direction. |
| “What does the rate of change describe?” | Distinguishes a long-term trend from one hot year, and per-decade change from a yearly value. |
| “Where do these data come from? What would the station add?” | Distinguishes a reanalysis from a thermometer at the point; recognises the second record, gaps and possible disagreement. |
| Open “How we checked this”. “What does p-value tell you here?” | Does not interpret p as the probability that the claim is false, or significance as importance. |
| “What does the confidence interval describe? What would a wider interval mean?” | Uncertainty in the estimated rate, not all observed years or a guaranteed future range. |
| “Why do we check several start and end years?” | Understands dependence on the selected period, not voting among different locations. |
| Find “anomaly” in “Words in this check”. “What else would you need to interpret an anomaly?” | Identifies the reference-period average. Do not call the absolute values on the historical chart anomalies. |
| Open Lviv rainfall. “What can you conclude now?” | Understands Not proven as insufficient evidence, not proof of no change; recognises no suitable station. |
| “What would you click if a word were unclear?” Then allow the help buttons/glossary. | Finds help without instruction. Record how the explanation changes after opening it, and which term remains unclear. |
| If the waiting estimate is visible: “What does this number promise?” | Understands it is conditional and not a guaranteed detection date. |

If the reader gets stuck, record the first interpretation before helping. Then point to
help once and ask “How would you explain it now?” Avoid asking “Do you understand?” or
suggesting the correct interpretation in the question.

## Blank session record

Copy this block once for each reader (3 required, up to 5). Leave unperformed sessions marked pending.
Do not replace real reader sessions with browser tests, a simulated conversation or invented quotes.

- Reader ID: R__
- Status: **pending**
- Date / facilitator:
- Build commit / code PR:
- Device / viewport:
- English UI comprehension / relevant prior familiarity:
- Permission for anonymous notes: pending
- Cases and help actually shown:

| Task or term | First explanation in reader's own words | Exact confusing word / action | Explanation after help | Change needed |
|---|---|---|---|---|
| Claim, trend and units | Pending | Pending | Pending | Pending |
| Reanalysis | Pending | Pending | Pending | Pending |
| Witness station | Pending | Pending | Pending | Pending |
| p-value | Pending | Pending | Pending | Pending |
| Confidence interval | Pending | Pending | Pending | Pending |
| Period robustness | Pending | Pending | Pending | Pending |
| Anomaly / reference period | Pending | Pending | Pending | Pending |
| Not proven / waiting | Pending | Pending | Pending | Pending |
| Finding and operating help | Pending | Pending | Pending | Pending |

Do not infer answers for skipped tasks. Mark them “not shown” with the reason.

## Findings and revisions

Current findings: **none collected**. This is not a statement that the copy is understandable.
After the sessions, record one row for each problem, including repeated misunderstandings.

| Reader IDs | Evidence / observed misunderstanding | Original text | Revised text | Changed UI path / commit | Recheck outcome |
|---|---|---|---|---|---|
| Pending | Pending | Pending | Pending | Pending | Pending |

If no wording change is justified, explain that conclusion with the actual notes rather than
claiming there were no issues. A small qualitative check does not establish a population success rate.

## Completion checklist

- [ ] Code PR integrated: all seven definitions available in the UI and shared from one module.
- [ ] At least 3 and at most 5 actual reader sessions recorded, with first interpretations and confusion points.
- [ ] Identified wording problems fixed without changing scientific meanings or hiding caveats.
- [ ] Changed wording rechecked and recorded, with any remaining limitations.
- [ ] Method-panel copy coordinated with #41 after that panel is integrated.

Automated keyboard, mobile and data-preservation checks support implementation review. They
are separate from the human sessions required by issue #8. Do not close the issue until
its reader-feedback acceptance criteria are satisfied.
