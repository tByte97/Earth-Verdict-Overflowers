import type { CheckResult } from './types';

export function number(value: number | null | undefined, signed = false) {
  if (value == null || !Number.isFinite(value)) return 'Not supplied';
  const formatted = new Intl.NumberFormat('en', {
    maximumSignificantDigits: 5,
    notation: value !== 0 && Math.abs(value) < 0.0001 ? 'scientific' : 'standard',
  }).format(value);
  return signed && value > 0 ? `+${formatted}` : formatted;
}
export const seasons = [['year', 'Whole year'], ['DJF', 'Winter · Dec–Feb'], ['MAM', 'Spring · Mar–May'], ['JJA', 'Summer · Jun–Aug'], ['SON', 'Autumn · Sep–Nov'], ...Array.from({ length: 12 }, (_, i) => [String(i + 1), new Intl.DateTimeFormat('en', { month: 'long' }).format(new Date(2000, i, 1))])];
export const seasonName = (season: CheckResult['case']['season']) => seasons.find(([value]) => value === String(season))?.[1].split(' · ')[0] ?? String(season);
export const coords = (lat: number, lon: number) => `${Math.abs(lat)}° ${lat >= 0 ? 'N' : 'S'}, ${Math.abs(lon)}° ${lon >= 0 ? 'E' : 'W'}`;

// p in words, using only "less than" steps; the exact p stays in its own tile.
export function chanceInWords(p: number, alpha: number) {
  if (p >= alpha) return 'A pattern like this can come from natural ups and downs alone, so on its own it does not show a real trend.';
  const step = p < 0.001 ? '1 in 1,000' : p < 0.01 ? '1 in 100' : p < 0.05 ? '1 in 20' : undefined;
  return step ? `If nothing were really changing, a pattern this steady would turn up by chance less than ${step} times.`
    : `If nothing were really changing, a pattern this steady would turn up by chance less often than the ${alpha} threshold allows.`;
}
export const period = (r: CheckResult) => `${r.case.start_year}–${r.case.end_year} · ${r.case.season}`;
const GIOVANNI_HOME = 'https://giovanni.gsfc.nasa.gov/giovanni/';

export function safeUrl(value: string) {
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? url.href : undefined; }
  catch { return undefined; }
}

export function provenanceLink(value: string): { href: string; label: string } | undefined {
  const href = safeUrl(value);
  if (!href) return undefined;
  try {
    const url = new URL(href);
    if (url.hostname === 'api.giovanni.earthdata.nasa.gov' && url.pathname.startsWith('/timeseries')) {
      return { href: GIOVANNI_HOME, label: 'Giovanni (sign-in needed for the raw request)' };
    }
  } catch { /* fall through */ }
  return { href, label: 'Open source' };
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
    unit = path === 'detection_history' ? 'not supplied by this response' : /\.(start_year|end_year|emerged_year)$/.test(path) ? 'calendar year' : /\.(min_observations|n_observations)$/.test(path) ? 'observed years' : path.endsWith('.correction') ? 'not applicable · test not performed' : 'dimensionless';
  }
  if (path.startsWith('extrapolation.')) {
    context = `${r.extrapolation?.from_year}–${r.extrapolation?.years.at(-1)} · Illustration, not a forecast`;
    if (/years\.\d+$/.test(path) || path.endsWith('from_year')) unit = 'calendar year';
    else if (path.endsWith('multiplier')) unit = 'dimensionless';
    else unit = r.variable.units;
  }
  if (path.startsWith('scenarios.')) {
    context = `relative to ${r.scenarios?.baseline_period} · ${r.scenarios?.synthetic ? 'Stylised scenario illustration' : 'Conditional model scenario'}, not a forecast`;
    unit = /years\.\d+$/.test(path) ? 'calendar year' : path.endsWith('baseline_n_years') ? 'observed years' : r.variable.units;
    if (path.endsWith('baseline_value')) context = `Baseline mean · ${r.scenarios?.baseline_period}`;
    else if (path.endsWith('baseline_n_years')) context = `Baseline observations · ${r.scenarios?.baseline_period}`;
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

function parseUrl(value: string): URL | undefined {
  try { return new URL(value); } catch { return undefined; }
}

function isWitnessProvenance(source: CheckResult['provenance'][number]): boolean {
  const url = parseUrl(source.url);
  return url?.hostname === 'www.ncei.noaa.gov' && !url.pathname.includes('climate-at-a-glance');
}

function isScenarioProvenance(source: CheckResult['provenance'][number]): boolean {
  return parseUrl(source.url)?.hostname === 'ds.nccs.nasa.gov' || source.source === 'NASA NCCS';
}

export function sourceIndex(path: string, r: CheckResult): number | undefined {
  // Only measured series/station metadata link to a provider. Derived quantities link
  // to a method record, never to the first provider or free-text `what` heuristics.
  if (sourceMethod(path)) return undefined;
  const [root, field] = path.split('.');
  if (root === 'provenance' && Number.isInteger(Number(field)) && r.provenance[Number(field)]) return Number(field);
  if (root !== 'witness' && root !== 'series') return undefined;
  const matches = r.provenance.flatMap((source, index) => {
    const matched = root === 'witness' ? isWitnessProvenance(source) : !isWitnessProvenance(source) && !isScenarioProvenance(source);
    return matched ? [index] : [];
  });
  return matches.length === 1 ? matches[0] : undefined;
}

export function seriesSourceName(r: CheckResult): string {
  const index = sourceIndex('series', r);
  return index !== undefined ? r.provenance[index].source : 'Primary data';
}
