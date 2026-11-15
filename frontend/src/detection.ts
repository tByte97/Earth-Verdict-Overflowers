import type { CheckResult } from './types';

export function baselineDetection(result: CheckResult): number | null | undefined {
  const detection = result.detection;
  if (!detection) return undefined;
  const index = detection.multipliers.indexOf(1);
  return index < 0 ? undefined : detection.years_needed[index];
}

export function waitingExplanation(result: CheckResult): string {
  if (result.years_to_wait != null) {
    return 'Additional observations at the observed rate, conditional on current variability. This is not a prediction or a guarantee of detection.';
  }
  if (result.verdict !== 'not_proven') return 'No additional waiting estimate applies to this resolved claim.';
  if (result.reason === 'sources_disagree') return 'An additional waiting estimate is not determined when the sources disagree.';
  if (result.reason === 'no_variation') return 'No waiting estimate applies: the value does not change here in this season.';
  const needed = baselineDetection(result);
  if (needed != null && result.detection && needed <= result.detection.n_years) {
    return 'The simulated detection duration has already been reached, but the observed trend remains unproven. More waiting cannot be inferred from this estimate.';
  }
  return 'The backend has not determined an additional waiting estimate. This does not mean zero years or that a trend has been established.';
}

// Presentation interpolation required by the Detection contract in PR #17.
// Exact nodes are returned unchanged; missing nodes are never bridged or treated as zero.
export function interpolateDetection(
  detection: NonNullable<CheckResult['detection']>, multiplier: number,
): { years: number | null; interpolated: boolean } {
  const { multipliers, years_needed: years } = detection;
  if (!Number.isFinite(multiplier) || multiplier <= 0 || multipliers.length !== years.length) {
    return { years: null, interpolated: false };
  }
  const exact = multipliers.indexOf(multiplier);
  if (exact >= 0) return { years: years[exact], interpolated: false };
  for (let i = 0; i < multipliers.length - 1; i++) {
    const left = multipliers[i]; const right = multipliers[i + 1];
    if (!(left > 0 && left < multiplier && multiplier < right)) continue;
    const low = years[i]; const high = years[i + 1];
    if (low == null || high == null || low <= 0 || high <= 0) return { years: null, interpolated: false };
    const position = (Math.log(multiplier) - Math.log(left)) / (Math.log(right) - Math.log(left));
    return { years: Math.exp(Math.log(low) + position * (Math.log(high) - Math.log(low))), interpolated: true };
  }
  return { years: null, interpolated: false };
}
