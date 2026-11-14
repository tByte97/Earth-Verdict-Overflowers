import type { CheckResult } from './types';

export function number(value: number | null | undefined, signed = false) {
  if (value == null || !Number.isFinite(value)) return 'Not supplied';
  const formatted = new Intl.NumberFormat('en', {
    maximumSignificantDigits: 5,
    notation: value !== 0 && Math.abs(value) < 0.0001 ? 'scientific' : 'standard',
  }).format(value);
  return signed && value > 0 ? `+${formatted}` : formatted;
}
export const period = (r: CheckResult) => `${r.case.start_year}–${r.case.end_year} · ${r.case.season}`;
export function safeUrl(value: string) {
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? url.href : undefined; }
  catch { return undefined; }
}

export function numericFields(value: unknown, prefix = ''): [string, number | null][] {
  if (typeof value === 'number' || value === null) return [[prefix, value]];
  if (!value || typeof value !== 'object') return [];
  return Object.entries(value).flatMap(([key, child]) => numericFields(child, prefix ? `${prefix}.${key}` : key));
}

export function fieldContext(path: string, r: CheckResult): { unit: string; context: string } {
  let context = period(r);
  let unit = 'Not supplied by backend';
  const window = /^robustness\.(\d+)\./.exec(path);
  if (window) { const row = r.robustness[Number(window[1])]; context = `${row.start_year}–${row.end_year} · ${r.case.season}`; }
  if (/\.(lat|lon)$/.test(path)) { unit = 'degrees'; context = 'Location'; }
  else if (path.endsWith('distance_km')) { unit = 'km'; context = 'Distance to station'; }
  else if (/\.(year|start_year|end_year|from_year)$/.test(path)) unit = 'calendar year';
  else if (/slope_per_decade$/.test(path) || /ci_(low|high)$/.test(path)) unit = `${r.variable.units} / decade`;
  else if (/slope_per_year$/.test(path)) unit = `${r.variable.units} / year`;
  else if (/\.(value|intercept|residual_sd)$/.test(path)) unit = r.variable.units;
  else if (/\.(p|tau|z|r1|phi|r2|coverage)$/.test(path)) unit = 'dimensionless';
  else if (path.endsWith('n_eff')) unit = 'effective observations';
  else if (path.startsWith('robustness_summary.')) unit = 'windows';
  else if (path === 'years_to_wait') unit = 'additional years (conditional estimate)';
  else if (path === 'case.season') unit = 'calendar month';
  else if (path === 'detection.n_years') unit = 'observed years';
  else if (/^detection\.multipliers\./.test(path)) unit = 'rate multiplier · dimensionless';
  else if (/^detection\.years_needed\./.test(path)) unit = 'total years needed · conditional estimate';
  if (path.startsWith('detection.')) context += ' · Detection experiment, not a forecast';
  if (path.startsWith('extrapolation.')) {
    context = `${r.extrapolation?.from_year}–${r.extrapolation?.years.at(-1)} · Illustration, not a forecast`;
    if (/years\.\d+$/.test(path) || path.endsWith('from_year')) unit = 'calendar year';
    else if (path.endsWith('multiplier')) unit = 'dimensionless';
    else unit = r.variable.units;
  }
  if (path.startsWith('scenarios.')) {
    context = `relative to ${r.scenarios?.baseline_period} · Synthetic scenarios, not a forecast`;
    unit = /years\.\d+$/.test(path) ? 'calendar year' : r.variable.units;
    if (path.endsWith('baseline_value')) context = `Baseline mean · ${r.scenarios?.baseline_period}`;
  }
  return { unit, context };
}

export function sourceIndex(path: string, r: CheckResult): number | undefined {
  const index = path.startsWith('witness.')
    ? r.provenance.findIndex(source => /station|NOAA/i.test(source.what + source.source))
    : path.startsWith('scenarios.')
      ? r.provenance.findIndex(source => /future|scenario/i.test(source.what))
      : r.provenance.findIndex(source => !/station|future|scenario/i.test(source.what));
  return index < 0 ? undefined : index;
}
