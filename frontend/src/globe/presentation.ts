import { ramp, type Ramp } from './paint';
import type { TrendCell } from './trends';

// How a trend layer reads on screen, by variable_id. Only words and colours live here; every number
// (period, units, slopes, p) comes from the layer itself.
export interface Presentation { palette: Ramp; up: string; down: string; upVerb: string; downVerb: string; driver?: string }

const presentations: Record<string, Presentation> = {
  air_temp: {
    palette: ramp(['#72a9ee', '#36629e', '#3b3a37', '#b1483d', '#f28466']),
    up: 'warmer', down: 'cooler', upVerb: 'gets warmer', downVerb: 'gets cooler',
    driver: 'Opposite temperature trends are rare at this scale. Look for local causes: irrigation cools summers, losing snow cover warms springs.',
  },
  precip: {
    palette: ramp(['#c9914f', '#7d5b31', '#3b3a37', '#2c7b73', '#63c7b8']),
    up: 'wetter', down: 'drier', upVerb: 'gets wetter', downVerb: 'gets drier',
    driver: 'One shift can do both: when Atlantic storms change their usual track, the regions they now reach get more rain and the ones they skip get less.',
  },
};
// A layer the frontend has no words for still renders, with a neutral ramp and no driver sentence.
const neutral: Presentation = { palette: ramp(['#7c8aa0', '#4a5262', '#3b3a37', '#6a6250', '#b3a789']), up: 'higher', down: 'lower', upVerb: 'goes up', downVerb: 'goes down' };
export const presentationOf = (variableId: string) => presentations[variableId] ?? neutral;

const seasonNames: Record<string, string> = { year: 'Year', DJF: 'Winter', MAM: 'Spring', JJA: 'Summer', SON: 'Autumn' };
export const seasonName = (season: string) => seasonNames[season] ?? season;
const seasonOrder = Object.keys(seasonNames);
export const bySeason = (a: string, b: string) => seasonOrder.indexOf(a) - seasonOrder.indexOf(b);

export const coords = (lat: number, lon: number) => `${Math.abs(lat)}° ${lat >= 0 ? 'N' : 'S'}, ${Math.abs(lon)}° ${lon >= 0 ? 'E' : 'W'}`;
export const signed = (value: number) => (value > 0 ? `+${value}` : value < 0 ? `−${-value}` : '0');
export const formatP = (p: number) => (p < 0.001 ? '<0.001' : String(p));
// Legend ends: a display scale, rounded for reading.
export const formatLimit = (x: number) => (x >= 10 ? x.toFixed(0) : x >= 1 ? String(Number(x.toFixed(1))) : String(Number(x.toPrecision(2))));

// Direction shared by all significant cells, if there is one. Reading signs is not a statistic.
export function commonDirection(cells: TrendCell[]): 'up' | 'down' | null {
  const significant = cells.filter(cell => cell.significant_fdr);
  if (!significant.length) return null;
  return significant.every(cell => cell.slope_per_decade > 0) ? 'up' : significant.every(cell => cell.slope_per_decade < 0) ? 'down' : null;
}
