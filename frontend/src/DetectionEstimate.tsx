import { useId, useState } from 'react';
import type { CheckResult } from './types';
import { interpolateDetection, waitingExplanation } from './detection';
import { number, period } from './format';

export function DetectionEstimate({ result }: { result: CheckResult }) {
  const sliderId = useId();
  const noteId = useId();
  const [multiplier, setMultiplier] = useState(1);
  const detection = result.detection;
  const usable = detection && detection.multipliers.length > 1 &&
    detection.multipliers.length === detection.years_needed.length &&
    detection.multipliers.every((value, i, values) => Number.isFinite(value) && value > 0 && (i === 0 || value > values[i - 1])) &&
    detection.multipliers.includes(1) &&
    detection.years_needed.every(value => value === null || Number.isFinite(value) && value > 0);

  if (!usable) return <section className="detection-estimate" aria-label="Detection duration"><h4>Detection duration</h4><p>No usable simulation points were supplied. No waiting duration is inferred.</p></section>;
  const estimate = interpolateDetection(detection, multiplier);
  return <section className="detection-estimate" aria-label="Detection duration">
    <h4>How long would detection take?</h4>
    <p className="help-text">Simulation illustration · not a forecast. The backend uses the same trend test as the verdict; this control only reads or interpolates its saved estimates.</p>
    <p className="section-context">Observed case: {period(result)} · {result.variable.units}</p>
    <label htmlFor={sliderId}>Hypothetical rate multiplier <output htmlFor={sliderId}>×{number(multiplier)}</output></label>
    <input id={sliderId} type="range" min={detection.multipliers[0]} max={detection.multipliers.at(-1)} step="0.01" value={multiplier} aria-describedby={noteId} onChange={event => setMultiplier(event.target.valueAsNumber)} />
    <div className="detection-presets" aria-label="Backend simulation points">
      {detection.multipliers.map(value => <button key={value} type="button" aria-pressed={value === multiplier} onClick={() => setMultiplier(value)}>×{number(value)}</button>)}
    </div>
    <dl className="statistics" aria-live="polite">
      <div><dt>Total observation duration needed · years</dt><dd data-testid="detection-total">{estimate.years === null ? 'Not determined for this rate' : number(estimate.years)}</dd></div>
      <div><dt>Observations already available · years</dt><dd>{number(detection.n_years)}</dd></div>
      <div><dt>Additional waiting at observed rate · years</dt><dd data-testid="detection-wait">{result.years_to_wait === null ? result.verdict === 'not_proven' ? 'Not determined' : 'Not applicable' : number(result.years_to_wait)}</dd></div>
    </dl>
    <p className="help-text" id={noteId}>{estimate.interpolated ? 'Interpolated illustration between adjacent backend points in log-rate / log-duration coordinates.' : estimate.years === null ? 'No estimate is supplied here; missing simulation points are not interpolated or treated as zero.' : 'Exact simulation point from the backend JSON.'} Changing the hypothetical rate does not change the historical verdict or its additional-waiting estimate.</p>
    <p className="help-text">{waitingExplanation(result)}</p>
    {result.verdict === 'not_proven' && <p className="help-text"><strong>Insufficient evidence does not mean no change.</strong></p>}
  </section>;
}
