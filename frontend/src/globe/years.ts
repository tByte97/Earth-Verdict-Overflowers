/// <reference types="vite/client" />
import { z } from 'zod';
import { isLive } from '../api';
import { coloursOf, niceStep } from '../colour';
import { gridOf, type Grid } from './paint';
import { presentationOf, seasonName, type Presentation } from './presentation';

// Year-by-year maps for the timeline (tools/build_grid_years.py): each cell's value in a year minus its own
// baseline average. The file also carries the 10-year averages and the ranks, so nothing is computed here.
const values = z.array(z.number().nullable());
const YearMapSchema = z.object({
  variable_id: z.string(), season: z.string(), units: z.string(), source: z.string().optional(),
  baseline: z.tuple([z.number().int(), z.number().int()]),
  years: z.array(z.number().int()).min(2), lat: z.array(z.number()).min(1), lon: z.array(z.number()).min(1),
  anomaly: z.array(values), mean: values, rank: z.array(z.number().int().nullable()),
  window: z.number().int().positive(), anomaly_smooth: z.array(values), mean_smooth: values,
  // Rows of cells fetched around Ukraine: the map fades out across them; `mean` and `rank` never include them.
  halo_cells: z.number().int().nonnegative().optional(),
}).refine(m => m.lat.length === m.lon.length && [m.anomaly, m.anomaly_smooth].every(rows => rows.length === m.years.length && rows.every(row => row.length === m.lat.length))
  && [m.mean, m.mean_smooth, m.rank].every(row => row.length === m.years.length), 'Year map arrays do not line up.');
export type YearMap = z.infer<typeof YearMapSchema>;

// Saved mode fetches the files as plain assets: they are large, and a JSON file needs no module wrapper.
const savedFiles = import.meta.glob<string>('../../../data/layers/years_*.json', { query: '?url', import: 'default', eager: true });

// Resolves to null when no year-by-year map exists for this variable and season: the timeline is then not offered.
export async function loadYearMap(variableId: string, season: string, signal: AbortSignal): Promise<YearMap | null> {
  let raw: unknown;
  if (!isLive) {
    const url = savedFiles[`../../../data/layers/years_${variableId}_${season}.json`];
    if (!url) return null;
    raw = await fetch(url, { signal }).then(response => (response.ok ? response.json() : null));
  } else {
    const response = await fetch(`/api/grid/years?${new URLSearchParams({ variable_id: variableId, season })}`, { signal: AbortSignal.any([signal, AbortSignal.timeout(20_000)]) });
    if (!response.ok) return null;
    raw = await response.json().catch(() => null);
  }
  const parsed = YearMapSchema.safeParse(raw);
  if (!parsed.success) throw new Error('Invalid year-by-year map.');
  return parsed.data.variable_id === variableId && parsed.data.season === season ? parsed.data : null;
}

export interface YearCell { lat: number; lon: number; i: number }
// Everything the globe and the timeline need, prepared once per map. `lim` is a display scale shared by all
// years, so a colour means the same thing in 1985 and in 2024.
export interface YearView { map: YearMap; grid: Grid<YearCell>; lim: number; pres: Presentation; most: string }
export function yearView(map: YearMap): YearView {
  const sorted = map.anomaly.flat().filter((v): v is number => v !== null).map(Math.abs).sort((a, b) => a - b);
  return { map, grid: gridOf(map.lat.map((lat, i) => ({ lat, lon: map.lon[i], i })), map.halo_cells), lim: niceStep(sorted[Math.floor(0.95 * (sorted.length - 1))] || 1),
    pres: presentationOf(map.variable_id), most: coloursOf(map.variable_id).most };
}

// One step of the timeline: a single year, or the average of the `window` years that end with it.
export interface Frame { view: YearView; index: number; smooth: boolean; cells: (number | null)[]; mean: number | null; period: string }
export function frameOf(view: YearView, index: number, smooth: boolean): Frame {
  const { map } = view, year = map.years[index];
  return { view, index, smooth, cells: (smooth ? map.anomaly_smooth : map.anomaly)[index], mean: (smooth ? map.mean_smooth : map.mean)[index],
    period: smooth ? `${year - map.window + 1}–${year}` : String(year) };
}
// The first step that has a map: the smoothed view starts once `window` years exist.
export const firstIndex = (view: YearView, smooth: boolean) => Math.max(0, (smooth ? view.map.mean_smooth : view.map.mean).findIndex(v => v !== null));

const amount = (value: number, units: string) => `${units === 'mm' ? Math.round(Math.abs(value)) : Math.abs(value).toFixed(1)} ${units}`;
export const signedAmount = (value: number, units: string) => `${value > 0 ? '+' : value < 0 ? '−' : ''}${amount(value, units)}`;
const ordinal = (n: number) => `${n}${n % 100 >= 11 && n % 100 <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[n % 10] ?? 'th'}`;

// Plain words for one step, e.g. "2024: 2.5 °C warmer than usual".
export function describe(frame: Frame) {
  const { view: { map, pres, most }, mean, period, smooth, index } = frame;
  const usual = `the ${map.baseline[0]}–${map.baseline[1]} average`;
  if (mean === null) return { headline: `${period}: no data`, detail: '' };
  const flat = amount(mean, map.units).startsWith('0 ') || amount(mean, map.units).startsWith('0.0 ');
  const headline = flat ? `${period}: about the same as usual` : `${period}: ${amount(mean, map.units)} ${mean > 0 ? pres.up : pres.down} than usual`;
  const rank = map.rank[index], count = map.rank.filter(r => r !== null).length;
  const place = smooth || rank === null ? '' : ` · ${rank === 1 ? `the ${most}` : `${ordinal(rank)} ${most}`} of ${count} ${map.season === 'year' ? 'years' : `${seasonName(map.season).toLowerCase()}s`}`;
  return { headline, detail: `Average over Ukraine, compared with ${usual}${place}` };
}
