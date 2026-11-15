import { coloursOf } from '../colour';
import type { CheckResult } from '../types';
import { cellAt, MERCATOR_LAT, type ImageCoordinates } from './paint';
import type { TrendView } from './TrendMap';

// The trend map answers for a case only when it is the same variable and season and the place lies inside
// the painted area (at least half strength, so not out in the fade).
export function caseOnMap(r: CheckResult, view: TrendView): boolean {
  const { place, variable_id, season } = r.case;
  if (place.place_id.startsWith('region:')) return false;
  if (view.layer.variable_id !== variable_id || view.layer.season !== String(season)) return false;
  const cell = cellAt(view.grid, place.lon, place.lat);
  return !!cell && (cell.fade ?? 1) >= 0.5;
}

// Where no map exists for a case, its own result is drawn at its place as one soft disc: the variable's
// colour when the trend is clear (verdict confirmed or refuted), white when it could be chance.
export interface CaseMark { lat: number; lon: number; radiusKm: number; direction: -1 | 0 | 1; variableId: string }
export function caseMark(r: CheckResult): CaseMark | null {
  const { place, variable_id } = r.case;
  // The whole planet has no place to mark.
  if (place.place_id === 'region:globe') return null;
  const slope = r.sen.slope_per_decade;
  return { lat: place.lat, lon: place.lon, radiusKm: place.place_id.startsWith('region:') ? 1400 : 320, variableId: variable_id,
    direction: r.verdict === 'not_proven' || slope === 0 ? 0 : slope > 0 ? 1 : -1 };
}
export const markColour = (mark: CaseMark) => coloursOf(mark.variableId).map(mark.direction === 0 ? 0.5 : mark.direction > 0 ? 0.92 : 0.08);

// A radial fade to nothing, laid over the map as an image around the place.
export function paintMark(mark: CaseMark): { url: string; coordinates: ImageCoordinates } {
  const size = 256, canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const g = canvas.getContext('2d')!;
  const [R, G, B] = markColour(mark), strength = mark.direction === 0 ? 0.62 : 0.85;
  const fill = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  for (const [stop, a] of [[0, 1], [0.35, 0.9], [0.7, 0.4], [1, 0]]) fill.addColorStop(stop, `rgba(${R},${G},${B},${a * strength})`);
  g.fillStyle = fill;
  g.fillRect(0, 0, size, size);
  const dLat = mark.radiusKm / 111, dLon = Math.min(170, mark.radiusKm / (111 * Math.max(0.2, Math.cos(mark.lat * Math.PI / 180))));
  const north = Math.min(MERCATOR_LAT, mark.lat + dLat), south = Math.max(-MERCATOR_LAT, mark.lat - dLat);
  return { url: canvas.toDataURL('image/png'), coordinates: [[mark.lon - dLon, north], [mark.lon + dLon, north], [mark.lon + dLon, south], [mark.lon - dLon, south]] };
}
