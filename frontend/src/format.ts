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
  else if (/^sen\.band\.\d+\.(low|mid|high)$/.test(path) || path === 'sen.pivot_value' || path === 'baseline.mean') unit = r.variable.units;
  else if (path === 'baseline.n_years') unit = 'observed years';
  else if (path === 'sen.pivot_year') unit = 'calendar year';
  else if (/\.(year|start_year|end_year|from_year)$/.test(path)) unit = 'calendar year';
  else if (/per_decade$/.test(path) || /ci_(low|high)$/.test(path)) unit = `${r.variable.units} / decade`;
  else if (/slope_per_year$/.test(path)) unit = `${r.variable.units} / year`;
  else if (/\.(value|intercept|residual_sd)$/.test(path)) unit = r.variable.units;
  else if (/\.(p|tau|z|r1|phi|r2|coverage)$/.test(path)) unit = 'dimensionless';
  else if (path.endsWith('common_years')) unit = 'shared observed years';
  else if (path.endsWith('n_eff')) unit = 'effective observations';
  else if (path.startsWith('robustness_summary.')) unit = 'windows';
  else if (path === 'years_to_wait') unit = 'additional years (conditional estimate)';
  else if (path === 'case.season') unit = 'calendar month';
  else if (path === 'detection.n_years') unit = 'observed years';
  else if (/^detection\.multipliers\./.test(path)) unit = 'rate multiplier · dimensionless';
  else if (/^detection\.years_needed\./.test(path)) unit = 'total years needed · conditional estimate';
  if (path.startsWith('detection.')) context += ' · Detection experiment, not a forecast';
  if (path === 'detection_history' || path.startsWith('detection_history.')) {
    const prefix = /^detection_history\.points\.(\d+)\./.exec(path);
    const point = prefix ? r.detection_history?.points[Number(prefix[1])] : undefined;
    context = `${r.detection_history?.start_year ?? r.case.start_year}–${point?.end_year ?? r.case.end_year} · ${r.case.season} · Observed prefix test; not a verdict or forecast`;
    unit = path === 'detection_history' ? 'not supplied by this response' : /\.(start_year|end_year)$/.test(path) ? 'calendar year' : /\.(min_observations|n_observations)$/.test(path) ? 'observed years' : path.endsWith('.correction') ? 'not applicable · test not performed' : 'dimensionless';
  }
  if (path.startsWith('extrapolation.')) {
    context = `${r.extrapolation?.from_year}–${r.extrapolation?.years.at(-1)} · Illustration, not a forecast`;
    if (/years\.\d+$/.test(path) || path.endsWith('from_year')) unit = 'calendar year';
    else if (path.endsWith('multiplier')) unit = 'dimensionless';
    else unit = r.variable.units;
  }
  if (path.startsWith('scenarios.')) {
    context = `relative to ${r.scenarios?.baseline_period} · ${r.scenarios?.synthetic ? 'Stylised scenario illustration' : 'Conditional model scenario'}, not a forecast`;
    unit = /years\.\d+$/.test(path) ? 'calendar year' : r.variable.units;
    if (path.endsWith('baseline_value')) context = `Baseline mean · ${r.scenarios?.baseline_period}`;
  }
  return { unit, context };
}

export type MethodKind = 'statistics' | 'detection' | 'history' | 'extrapolation' | 'scenario';

export function sourceMethod(path: string): MethodKind | undefined {
  const [root, field] = path.split('.');
  if (root === 'detection_history') return 'history';
  if (root === 'detection' || root === 'years_to_wait') return 'detection';
  if (root === 'extrapolation') return 'extrapolation';
  if (root === 'scenarios') return 'scenario';
  if (['sen', 'mk', 'ols', 'robustness', 'robustness_summary', 'steps'].includes(root) ||
    root === 'witness' && ['sen', 'mk', 'rates', 'coverage'].includes(field)) return 'statistics';
  return undefined;
}

export function sourceIndex(path: string, r: CheckResult): number | undefined {
  // Only measured series/station metadata link to a provider. Derived quantities link
  // to a method record, never to the first provider or free-text `what` heuristics.
  if (sourceMethod(path)) return undefined;
  const [root, field] = path.split('.');
  if (root === 'provenance' && Number.isInteger(Number(field)) && r.provenance[Number(field)]) return Number(field);
  const host = root === 'witness' ? 'www.ncei.noaa.gov' : root === 'series' ? 'power.larc.nasa.gov' : undefined;
  if (!host) return undefined;
  const matches = r.provenance.flatMap((source, index) => {
    try { return new URL(source.url).hostname === host ? [index] : []; } catch { return []; }
  });
  return matches.length === 1 ? matches[0] : undefined;
}
