import type { CheckResult } from './types';
import { number } from './format';
import { waitingExplanation } from './detection';

export function UncertaintyPanel({ result, onSource }: { result: CheckResult; onSource: () => void }) {
  if (result.verdict !== 'not_proven') return null;
  return <section className="uncertainty-panel" aria-label="Why not proven">
    <p><strong>Not enough evidence does not mean no change.</strong> A trend may be present but not established against the background of variability.</p>
    <p className="waiting-value">Additional observations at the observed rate: <strong data-testid="visible-wait">{result.years_to_wait === null ? 'Not determined' : `${number(result.years_to_wait)} years`}</strong>.</p>
    <p className="help-text">{waitingExplanation(result)}</p>
    <button type="button" className="text-button" onClick={onSource}>How this waiting estimate is calculated</button>
  </section>;
}
