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
  const window = /^robustness\.(\d+)\./.exec(path);
  if (window) { const row = r.robustness[Number(window[1])]; context = `${row.start_year}–${row.end_year} · ${r.case.season}`; }
  if (path.endsWith('.value') && r.presentation?.baseline) context += ` · relative to ${r.presentation.baseline}`;
  let unit = 'Not supplied by backend';
  if (/\.(lat|lon)$/.test(path)) { unit = 'degrees'; context = 'Location'; }
  else if (path.endsWith('distance_km')) { unit = 'km'; context = 'Distance to station'; }
  else if (/year$/.test(path)) unit = 'calendar year';
  else if (/slope_per_decade$/.test(path)) unit = `${r.variable.units} / decade`;
  else if (/slope_per_year$/.test(path)) unit = `${r.variable.units} / year`;
  else if (/ci_(low|high)$/.test(path)) unit = (path.startsWith('witness.') ? r.presentation?.ci_units?.witness : r.presentation?.ci_units?.sen) || 'Interval units not supplied by backend';
  else if (/\.(value|intercept)$/.test(path)) unit = r.variable.units;
  else if (/\.(p|tau|z|r1|r2)$/.test(path)) unit = 'dimensionless';
  else if (path.endsWith('n_eff')) unit = 'effective observations';
  else if (path.startsWith('robustness_summary.')) unit = 'windows';
  else if (path === 'years_to_wait') unit = 'additional years (conditional estimate)';
  else if (path === 'case.season') unit = 'calendar month';
  return { unit, context };
}
