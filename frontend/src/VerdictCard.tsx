import { useId, useRef } from 'react';
import type { CheckResult } from './types';
import { fieldContext, number, numericFields, period, safeUrl, sourceIndex, sourceMethod, type MethodKind } from './format';
import { DetectionSimulator } from './DetectionSimulator';
import { UncertaintyPanel } from './UncertaintyPanel';
import { waitingExplanation } from './detection';
import { StepPipeline } from './steps/StepPipeline';

const verdicts = { confirmed: ['Confirmed', '✓'], refuted: ['Refuted', '×'], not_proven: ['Not proven', '?'] };
const reasons: Record<string, string> = {
  significant_trend: 'The evidence supports the direction of change in your claim.',
  opposite_trend: 'The evidence shows a trend in the opposite direction to your claim.',
  not_significant: 'The trend is not clear enough to distinguish from year-to-year variation.',
  short_series: 'There are too few observations to establish a reliable trend.',
  sources_disagree: 'The two data sources disagree about the direction of change.',
  not_robust: 'The conclusion depends too much on which years are selected.',
};
const agreements = {
  agree: ['Sources agree', 'The ground station supports the result.'],
  one_source: ['One source', 'Only one source provides evidence for the trend.'],
  disagree: ['Sources disagree', 'The ground station and primary source disagree.'],
  no_station: ['No station', 'No suitable ground station is available.'],
};

export function VerdictCard({ result: r, saved }: { result: CheckResult; saved: boolean }) {
  const headingId = useId();
  const sourceId = useId();
  const methodLabels: Record<MethodKind, string> = { statistics: 'Backend statistics', detection: 'Detection simulation', history: 'Prefix trend analysis', extrapolation: 'Trend extrapolation', scenario: r.scenarios?.synthetic ? 'Stylised scenario' : 'Model scenario' };
  const sourceDetails = useRef<HTMLDetailsElement>(null);
  const agreement = agreements[r.witness?.agreement ?? 'no_station'];
  const [label, icon] = verdicts[r.verdict];
  // The raw monthly record (hundreds of values) is shown by the raw step's mini chart, not as table rows.
  const fields = numericFields(r).filter(([path]) => !/^steps\.\d+\.monthly\./.test(path));
  const historical = fields.filter(([path]) => !/^(scenarios|extrapolation)\./.test(path));
  const future = fields.filter(([path]) => /^(scenarios|extrapolation)\./.test(path));
  function openSources(index?: number | MethodKind) {
    if (sourceDetails.current) {
      sourceDetails.current.open = true;
      const target = index === undefined ? sourceDetails.current : document.getElementById(`${sourceId}-${index}`);
      target?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }
  function renderNumbers(rows: [string, number | null][]) {
    return <div className="table-scroll numeric-table"><table><thead><tr><th>JSON field</th><th>Exact value</th><th>Units</th><th>Period / context</th><th>Source</th></tr></thead><tbody>{rows.map(([path, value]) => {
      const ctx = fieldContext(path, r);
      const index = sourceIndex(path, r);
      const method = sourceMethod(path);
      const missing = path === 'years_to_wait' ? 'Not determined (null)' : path.startsWith('detection_history.points.') ? 'Test not performed (null)' : path.startsWith('detection.years_needed.') ? 'No simulation estimate (null)' : 'Not supplied (null)';
      return <tr key={path}><th><code>{path}</code></th><td>{value === null ? missing : String(value)}</td><td>{ctx.unit}</td><td>{ctx.context}</td><td>{method ? <button type="button" className="text-button" onClick={() => openSources(method)}>{methodLabels[method]}</button> : index === undefined ? 'Source mapping unavailable' : <button type="button" className="text-button" onClick={() => openSources(index)}>{r.provenance[index].source}</button>}</td></tr>;
    })}</tbody></table></div>;
  }
  return <article className="verdict-card" aria-labelledby={headingId}>
    <div className="card-top"><span className="eyebrow">Past observations · Verdict</span><span className="tag">{r.meta?.stub ? 'Provisional statistics' : saved ? 'Saved backend response' : 'Backend response'}</span></div>
    <h2 id={headingId} className="claim">{r.case.claim_text}</h2>
    <p className="context">{r.case.place.name} <span>·</span> {r.variable.label} <span>·</span> {period(r)}</p>
    <section className={`verdict verdict-${r.verdict}`} aria-label="Verdict">
      <span className="verdict-symbol" aria-hidden="true">{icon}</span>
      <div><h3>{label}</h3><p>{reasons[r.reason] ?? 'The backend returned an unrecognised reason. Inspect the response details.'}</p></div>
    </section>
    <UncertaintyPanel result={r} onSource={() => openSources('detection')} />
    <div className="headline-metric">
      <span className="eyebrow">Rate of change · Sen’s slope</span>
      <div className="metric-value">{number(r.sen.slope_per_decade, true)} <span>{r.variable.units} / decade</span></div>
      <p>Estimated over {period(r)}</p>
      <button type="button" className="text-button" aria-controls={sourceId} onClick={() => openSources()}>Data sources <span aria-hidden="true">↗</span></button>
    </div>
    <div className={`witness witness-${r.witness?.agreement ?? 'no_station'}`}><span className="witness-dot" aria-hidden="true" /><div><strong>{agreement[0]}</strong><p>{agreement[1]}{r.witness ? ` Station: ${r.witness.station.name}.` : ''}</p></div></div>
    {r.variable.caveat && <p className="data-note">{r.variable.caveat}</p>}
    {r.meta?.stub && <p className="data-note"><strong>Provisional statistics.</strong> Supplied by the team’s backend snapshot; results may change when the final statistics engine is ready.</p>}
    <StepPipeline result={r} onSource={openSources} />
    <details className="technical">
      <summary>How we checked this <span>Methods, uncertainty & full precision</span></summary>
      <div className="detail-body">
        <p className="section-context">{period(r)} · Absolute observations; no anomaly baseline applies to this historical trend.</p>
        <h4>Methods & uncertainty</h4>
        <div className="table-scroll"><table><thead><tr><th>Method</th><th>Change per year</th><th>p · dimensionless</th></tr></thead><tbody>
          <tr><th>Sen / Mann–Kendall</th><td>{number(r.sen.slope_per_year)} {r.variable.units} / year</td><td>{number(r.mk.p)}</td></tr>
          <tr><th>Regression / t-test</th><td>{number(r.ols.slope_per_year)} {r.variable.units} / year</td><td>{number(r.ols.p)}</td></tr>
        </tbody></table></div>
        <dl className="statistics">
          <div><dt>Sen 95% confidence interval</dt><dd>{number(r.sen.ci_low)} to {number(r.sen.ci_high)} · {r.variable.units} / decade</dd></div>
          <div><dt>Residual autocorrelation r₁ · dimensionless</dt><dd>{number(r.detection?.phi)}</dd></div>
          <div><dt>Autocorrelation correction</dt><dd>{r.mk.correction ?? 'Not supplied'}</dd></div>
          <div><dt>Period robustness</dt><dd>{r.robustness_summary.significant} of {r.robustness_summary.total} windows significant</dd></div>
          <div><dt>Additional waiting · years</dt><dd>{r.years_to_wait === null ? r.verdict === 'not_proven' ? 'Not determined' : 'Not applicable' : number(r.years_to_wait)}</dd></div>
        </dl>
        <p className="help-text">{waitingExplanation(r)}</p>
        <p className="help-text"><strong>p-value:</strong> under the no-trend hypothesis and test assumptions, how likely a test statistic at least this extreme would be. It is not the probability that the claim is false.</p>
        <p className="help-text"><strong>95% confidence interval:</strong> the uncertainty range for the slope under the method’s assumptions. <strong>r₁:</strong> how strongly neighbouring residuals are related. This value comes from <code>detection.phi</code>, bounded to 0–0.9 by the backend for its detection estimate; it is not a measurement of raw-series autocorrelation.</p>
        <h4>Stability across periods</h4>
        <div className="table-scroll"><table><thead><tr><th>Period</th><th>Sen · {r.variable.units} / decade</th><th>p · dimensionless</th><th>Significant</th></tr></thead><tbody>{r.robustness.map((row, i) => <tr key={i}><th>{row.start_year}–{row.end_year} · {r.case.season}</th><td>{number(row.slope_per_decade, true)}</td><td>{number(row.p)}</td><td>{row.significant ? 'Yes' : 'No'}</td></tr>)}</tbody></table></div>
        <h4>All numeric response fields</h4>
        <p className="help-text">Exact values received from JSON, including station observations and secondary statistics. Missing values remain missing.</p>
        {renderNumbers(historical)}
        <details className="raw"><summary>Original JSON response · includes separately labelled future inputs</summary><pre>{JSON.stringify(r, null, 2)}</pre></details>
      </div>
    </details>
    <DetectionSimulator key={JSON.stringify(r.case)} result={r} onHistorySource={() => openSources('history')} onDetectionSource={() => openSources('detection')} />
    {future.length > 0 && <details className="future-reference">
      <summary>Future illustrations · separate from the verdict <span>Conditional estimates, not a forecast</span></summary>
      <div className="detail-body">
        <p className="caution"><strong>These values do not determine the historical verdict.</strong> Extrapolation is an illustration, not a forecast. Scenario curves are {r.scenarios?.synthetic ? 'stylised placeholders, not CMIP6 model outputs' : 'conditional model scenarios'}.</p>
        {r.extrapolation && <p className="help-text">{r.extrapolation.note}</p>}
        {r.scenarios && <p className="help-text">{r.scenarios.source} · Scenario anomaly baseline: {r.scenarios.baseline_period}; baseline mean: {number(r.scenarios.baseline_value)} {r.variable.units}.</p>}
        {renderNumbers(future)}
      </div>
    </details>}
    <details className="sources" ref={sourceDetails} id={sourceId}>
      <summary>Data sources <span>Provenance & reproducibility</span></summary>
      <div className="detail-body">
        {r.meta?.stub && <p className="caution">The observations come from the team’s shared data files. Statistical outputs are provisional (<code>meta.stub: true</code>). Stylised future curves are not observations.</p>}
        <section className="source-record" id={`${sourceId}-statistics`}><h4>Backend statistics</h4><p>Calculated by {r.meta.stats_engine}. Statistical estimates and station-rate comparisons are derived from input observations, not raw provider readings.</p></section>
        <section className="source-record" id={`${sourceId}-detection`}><h4>Detection simulation</h4><p>The backend simulates the trend test using the supplied residual variability, autocorrelation and rate. These conditional durations are not NASA POWER measurements or forecasts. Inputs remain in the exact-value table.</p></section>
        <section className="source-record" id={`${sourceId}-history`}><h4>Prefix trend analysis</h4><p>The backend repeats its Sen / autocorrelation-corrected Mann–Kendall analysis on the original, unrounded annual observations through each end year, with a fixed start year. It retains missing calendar years. This is an observed-prefix test, not the detection power simulation or a separate claim verdict.</p><p>Inputs: the case’s primary observation provider listed below. Published annual values are rounded for display; prefix p-values retain the backend precision, while the main mk.p is formatted to three significant digits. Method: {r.detection_history?.method ?? 'Not supplied'}.</p></section>
        <section className="source-record" id={`${sourceId}-extrapolation`}><h4>Trend extrapolation</h4><p>Backend-generated what-if values derived from the observed trend and its uncertainty; not provider observations or a forecast.</p></section>
        <section className="source-record" id={`${sourceId}-scenario`}><h4>{methodLabels.scenario}</h4><p>{r.scenarios?.synthetic ? 'Stylised placeholder values, not measured data or CMIP6 output.' : r.scenarios?.source ?? 'No scenario data supplied.'}</p></section>
        {!r.provenance.length && <p>No provenance supplied by the backend. These values cannot yet be independently traced.</p>}
        {r.provenance.map((source, i) => <section className="source-record" key={i} id={`${sourceId}-${i}`}>
          <h4>{source.what}</h4><p><strong>{source.source}</strong> · {source.product}</p>
          <dl className="statistics"><div><dt>Version</dt><dd>{source.version ?? 'Not supplied'}</dd></div><div><dt>Retrieved / fixture created</dt><dd>{source.retrieved_at}</dd></div><div><dt>License</dt><dd>{source.license}</dd></div></dl>
          {safeUrl(source.url) ? <a href={safeUrl(source.url)} target="_blank" rel="noreferrer">Open source <span aria-hidden="true">↗</span></a> : <p>Source URL unavailable or unsafe.</p>}
        </section>)}
        <p className="help-text">Observation rows link to unambiguous recognised provider URLs. Derived statistics, detection simulations, extrapolations and scenario values link to their own method records above. Unknown or ambiguous provider mappings are explicitly left unmapped; they are never guessed from descriptions.</p>
      </div>
    </details>
  </article>;
}
