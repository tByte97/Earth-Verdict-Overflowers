import { useId, useRef } from 'react';
import type { CheckResult } from './types';
import { fieldContext, number, numericFields, period, safeUrl } from './format';

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

export function VerdictCard({ result: r, demo }: { result: CheckResult; demo: boolean }) {
  const headingId = useId();
  const sourceId = useId();
  const sourceDetails = useRef<HTMLDetailsElement>(null);
  const agreement = agreements[r.witness?.agreement ?? 'no_station'];
  const [label, icon] = verdicts[r.verdict];
  const fields = numericFields(r);
  function openSources() {
    if (sourceDetails.current) { sourceDetails.current.open = true; sourceDetails.current.scrollIntoView({ behavior: 'smooth', block: 'center' }); }
  }
  return <article className="verdict-card" aria-labelledby={headingId}>
    <div className="card-top"><span className="eyebrow">Past observations · Verdict</span><span className="tag">{demo ? 'Synthetic response' : 'Backend response'}</span></div>
    <h2 id={headingId} className="claim">{r.case.claim_text}</h2>
    <p className="context">{r.case.place.name} <span>·</span> {r.variable.label} <span>·</span> {period(r)}</p>
    <section className={`verdict verdict-${r.verdict}`} aria-label="Verdict">
      <span className="verdict-symbol" aria-hidden="true">{icon}</span>
      <div><h3>{label}</h3><p>{reasons[r.reason] ?? 'The backend returned an unrecognised reason. Inspect the response details.'}</p></div>
    </section>
    {r.verdict === 'not_proven' && <p className="caution"><strong>Not enough evidence does not mean no change.</strong> A trend may be present but not established against the background of variability.</p>}
    <div className="headline-metric">
      <span className="eyebrow">Rate of change · Sen’s slope</span>
      <div className="metric-value">{number(r.sen.slope_per_decade, true)} <span>{r.variable.units} / decade</span></div>
      <p>Estimated over {period(r)}{r.presentation?.baseline ? ` · relative to ${r.presentation.baseline}` : ''}</p>
      <button type="button" className="text-button" aria-controls={sourceId} onClick={openSources}>Data sources <span aria-hidden="true">↗</span></button>
    </div>
    <div className={`witness witness-${r.witness?.agreement ?? 'no_station'}`}><span className="witness-dot" aria-hidden="true" /><div><strong>{agreement[0]}</strong><p>{agreement[1]} {r.witness?.station.name}</p></div></div>
    <p className="data-note">{r.variable.caveat}</p>
    <details className="technical">
      <summary>How we checked this <span>Methods, uncertainty & full precision</span></summary>
      <div className="detail-body">
        <p className="section-context">{period(r)} · {r.presentation?.baseline ? `Anomaly baseline: ${r.presentation.baseline}` : 'Anomaly baseline: not supplied; no anomaly is derived in this view.'}</p>
        <h4>Methods & uncertainty</h4>
        <div className="table-scroll"><table><thead><tr><th>Method</th><th>Change per year</th><th>p · dimensionless</th></tr></thead><tbody>
          <tr><th>Sen / Mann–Kendall</th><td>{number(r.sen.slope_per_year)} {r.variable.units} / year</td><td>{number(r.mk.p)}</td></tr>
          <tr><th>Regression / t-test</th><td>{number(r.ols.slope_per_year)} {r.variable.units} / year</td><td>{number(r.ols.p)}</td></tr>
        </tbody></table></div>
        <dl className="statistics">
          <div><dt>Sen 95% confidence interval</dt><dd>{number(r.sen.ci_low)} to {number(r.sen.ci_high)} · {r.presentation?.ci_units?.sen ?? 'Interval units not supplied by backend'}</dd></div>
          <div><dt>Lag-one autocorrelation r₁ · dimensionless</dt><dd>{number(r.mk.r1)}</dd></div>
          <div><dt>Autocorrelation correction</dt><dd>{r.mk.correction ?? 'Not supplied'}</dd></div>
          <div><dt>Period robustness</dt><dd>{r.robustness_summary.significant} of {r.robustness_summary.total} windows significant</dd></div>
          <div><dt>Additional observations · years</dt><dd>{number(r.years_to_wait)}{r.years_to_wait != null ? ' · conditional on current rate and variability; not a prediction' : ''}</dd></div>
        </dl>
        <p className="help-text"><strong>p-value:</strong> under the no-trend hypothesis and test assumptions, how likely a test statistic at least this extreme would be. It is not the probability that the claim is false.</p>
        <p className="help-text"><strong>95% confidence interval:</strong> the uncertainty range for the slope under the method’s assumptions. <strong>r₁:</strong> how strongly neighbouring years are related.</p>
        <h4>Stability across periods</h4>
        <div className="table-scroll"><table><thead><tr><th>Period</th><th>Sen · {r.variable.units} / decade</th><th>p · dimensionless</th><th>Significant</th></tr></thead><tbody>{r.robustness.map((row, i) => <tr key={i}><th>{row.start_year}–{row.end_year} · {r.case.season}</th><td>{number(row.slope_per_decade, true)}</td><td>{number(row.p)}</td><td>{row.significant ? 'Yes' : 'No'}</td></tr>)}</tbody></table></div>
        <h4>All numeric response fields</h4>
        <p className="help-text">Exact values received from JSON, including station observations and secondary statistics. Missing values remain missing.</p>
        <div className="table-scroll numeric-table"><table><thead><tr><th>JSON field</th><th>Exact value</th><th>Units</th><th>Period / context</th></tr></thead><tbody>{fields.map(([path, value]) => { const ctx = fieldContext(path, r); return <tr key={path}><th><code>{path}</code></th><td>{value === null ? 'Not supplied (null)' : String(value)}</td><td>{ctx.unit}</td><td>{ctx.context}</td></tr>; })}</tbody></table></div>
        <details className="raw"><summary>Original JSON response</summary><pre>{JSON.stringify(r, null, 2)}</pre></details>
      </div>
    </details>
    <details className="sources" ref={sourceDetails} id={sourceId}>
      <summary>Data sources <span>Provenance & reproducibility</span></summary>
      <div className="detail-body">
        {demo && <p className="caution">These are synthetic fixtures, not downloaded NASA or NOAA measurements. Links identify intended data providers, not evidence for these demo numbers.</p>}
        {!r.provenance.length && <p>No provenance supplied by the backend. These values cannot yet be independently traced.</p>}
        {r.provenance.map((source, i) => <section className="source-record" key={i}>
          <h4>{source.what}</h4><p><strong>{source.source}</strong> · {source.product}</p>
          <dl className="statistics"><div><dt>Version</dt><dd>{source.version ?? 'Not supplied'}</dd></div><div><dt>Retrieved / fixture created</dt><dd>{source.retrieved_at}</dd></div><div><dt>License</dt><dd>{source.license}</dd></div></dl>
          {safeUrl(source.url) ? <a href={safeUrl(source.url)} target="_blank" rel="noreferrer">Open source <span aria-hidden="true">↗</span></a> : <p>Source URL unavailable or unsafe.</p>}
        </section>)}
        <p className="help-text">The primary source feeds Sen/Mann–Kendall, regression and period checks. Ground-station fields belong to the station source. Exact per-field provenance links require the backend to supply that mapping.</p>
      </div>
    </details>
  </article>;
}
