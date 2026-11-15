import type { CheckResult } from './types';

// The case file as CSV. Every cell is copied from the result as received: nothing is computed, rounded or
// filled in. A missing value is an empty cell. Keys are the JSON paths, so each number can be traced back.
type Cell = string | number | null | undefined;

// Quote when needed; text that a spreadsheet would run as a formula gets a leading apostrophe.
function cell(value: Cell) {
  if (value === null || value === undefined) return '';
  if (typeof value === 'number') return String(value);
  const text = /^[=+\-@\t\r]/.test(value) ? `'${value}` : value;
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}
const row = (...cells: Cell[]) => cells.map(cell).join(',');

export function caseCsv(r: CheckResult) {
  const units = r.variable.units;
  const station = new Map(r.witness?.series.map(point => [point.year, point.value]) ?? []);
  const band = new Map(r.sen.band.map(point => [point.year, point]));
  const header = [
    row('field', 'value', 'units'),
    row('case.claim_text', r.case.claim_text, ''),
    row('case.place.name', r.case.place.name, ''),
    row('case.place.lat', r.case.place.lat, 'degrees'),
    row('case.place.lon', r.case.place.lon, 'degrees'),
    row('variable.label', r.variable.label, ''),
    row('case.season', r.case.season, ''),
    row('case.start_year', r.case.start_year, 'calendar year'),
    row('case.end_year', r.case.end_year, 'calendar year'),
    row('verdict', r.verdict, ''),
    row('reason', r.reason, ''),
    row('sen.slope_per_decade', r.sen.slope_per_decade, `${units} / decade`),
    row('sen.ci_low', r.sen.ci_low, `${units} / decade`),
    row('sen.ci_high', r.sen.ci_high, `${units} / decade`),
    row('mk.p', r.mk.p, 'dimensionless'),
    row('mk.correction', r.mk.correction, ''),
    row('baseline.mean', r.baseline.mean, units),
    row('baseline.period', r.baseline.period, ''),
    row('witness.station.name', r.witness?.station.name ?? null, ''),
    row('witness.station.distance_km', r.witness?.station.distance_km ?? null, 'km'),
    ...r.provenance.flatMap((source, i) => [
      row(`provenance.${i}.what`, source.what, ''),
      row(`provenance.${i}.source`, source.source, ''),
      row(`provenance.${i}.product`, source.product, ''),
      row(`provenance.${i}.url`, source.url, ''),
    ]),
  ];
  const table = [
    row('year', `series.value (${units})`, `sen.band.mid (${units})`, `sen.band.low (${units})`, `sen.band.high (${units})`, `witness.series.value (${units})`),
    ...r.series.map(point => {
      const line = band.get(point.year);
      return row(point.year, point.value, line?.mid, line?.low, line?.high, station.get(point.year));
    }),
  ];
  return [...header, '', ...table].join('\r\n') + '\r\n';
}

export const caseCsvName = (r: CheckResult) =>
  `earth-verdict-${r.case.place.place_id}-${r.variable.id}-${r.case.season}-${r.case.start_year}-${r.case.end_year}.csv`.replace(/[^\w.-]+/g, '-');

export function downloadCaseCsv(r: CheckResult) {
  const url = URL.createObjectURL(new Blob([caseCsv(r)], { type: 'text/csv;charset=utf-8' }));
  const link = Object.assign(document.createElement('a'), { href: url, download: caseCsvName(r) });
  link.click();
  URL.revokeObjectURL(url);
}
