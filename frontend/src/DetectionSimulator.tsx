import { useId, useState } from 'react';
import type { CheckResult } from './types';
import { number } from './format';
import { DetectionEstimate } from './DetectionEstimate';
import { DetectionHistoryChart } from './DetectionHistoryChart';
import './uncertainty.css';

export function DetectionSimulator({ result, onHistorySource, onDetectionSource }: {
  result: CheckResult; onHistorySource: () => void; onDetectionSource: () => void;
}) {
  const history = result.detection_history;
  const [endYear, setEndYear] = useState(result.case.end_year);
  const id = useId();
  const selected = history?.points.find(point => point.end_year === endYear);
  return <details className="detection-simulator">
    <summary>Explore how evidence changes <span>Record length and hypothetical rate</span></summary>
    <div className="detail-body">
      <p className="caution"><strong>Statistical illustration · not a forecast.</strong> These controls do not change the case parameters, historical verdict or its additional-waiting estimate.</p>
      <h4>How much can a shorter record tell us?</h4>
      <details className="simulator-help"><summary>How to use this illustration</summary><ol><li>Move “Record through year” to keep only the earlier observations.</li><li>Each block is one end year: filled when p is below the threshold. p can rise or fall as years are added.</li><li>Return to the full record. A significant result for one period alone does not establish the claim: robustness and the station check still matter.</li></ol></details>
      {history && selected ? <>
        <p className="section-context">{result.case.place.name} · {result.variable.label} · {result.case.season}. Each prefix starts in {history.start_year} and uses only observations through its end year.</p>
        <label htmlFor={`${id}-end`}>Record through year <output htmlFor={`${id}-end`}>{endYear}</output></label>
        <input id={`${id}-end`} type="range" min={history.start_year} max={result.case.end_year} step="1" value={endYear} aria-describedby={`${id}-readout`} onChange={event => setEndYear(event.target.valueAsNumber)} />
        <div className="history-readout" id={`${id}-readout`} role="status" aria-live="polite" aria-atomic="true">
          <span>Selected period: <strong>{history.start_year}–{endYear}</strong> · <strong data-testid="prefix-count">{selected.n_observations}</strong> observed years</span>
          <span>p · dimensionless: <strong data-testid="prefix-p">{selected.p === null ? 'Not calculated' : number(selected.p)}</strong></span>
          <span data-testid="prefix-status">{selected.p === null ? `Too few observations: this illustration requires ${history.min_observations}.` : selected.p < history.alpha ? `Below ${history.alpha}: statistically significant in this period.` : `At or above ${history.alpha}: insufficient evidence in this period.`}</span>
        </div>
        <div className="history-actions"><button type="button" className="text-button" onClick={() => setEndYear(result.case.end_year)}>Return to full record</button><button type="button" className="text-button" onClick={onHistorySource}>How this period was checked</button></div>
        <DetectionHistoryChart history={history} result={result} endYear={endYear} />
        <p className="help-text">{result.variable.definition} Missing observations are not zero. p can move in either direction; a longer record does not guarantee significance. Hover a block to see its exact p; every value is also in the table.</p>
        <details className="history-values"><summary>Exact results for each period</summary><p className="help-text">Scroll the table sideways on a small screen to see every column.</p>
          <p className="help-text">p-values have no units; each row starts in {history.start_year}. No anomaly baseline applies to the p-value.</p>
          <div className="table-scroll"><table><thead><tr><th>End year</th><th>Observed years</th><th>Exact p</th><th>Correction</th><th>Result</th></tr></thead><tbody>{history.points.map(point => <tr key={point.end_year} aria-current={point.end_year === endYear ? 'true' : undefined}><th>{point.end_year}</th><td>{point.n_observations}</td><td>{point.p === null ? 'Not calculated (null)' : String(point.p)}</td><td>{point.correction ?? 'Test not performed'}</td><td>{point.status === 'short_series' ? 'Too few observations' : point.p! < history.alpha ? `p < ${history.alpha}` : `p ≥ ${history.alpha}`}</td></tr>)}</tbody></table></div>
        </details>
      </> : <p className="history-unavailable" role="status">Prefix results were not supplied by this backend response. The record-length slider is unavailable; no p-values are inferred.</p>}
      <div className="rate-experiment"><h4>What if the rate were different?</h4><p className="help-text">This separate experiment changes the estimated total duration needed for detection. It does not alter the observed-prefix chart above.</p><DetectionEstimate result={result} /><button type="button" className="text-button" onClick={onDetectionSource}>Detection simulation method & inputs</button></div>
    </div>
  </details>;
}
