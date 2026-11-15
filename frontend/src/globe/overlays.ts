import { coloursOf, css, type Rgb } from '../colour';
import type { CheckResult } from '../types';
import type { Co2Impact, EventResult } from '../events/schema';
import { cellAt, MERCATOR_LAT, type ImageCoordinates } from './paint';
import type { TrendView } from './TrendMap';
import { applyTexture, textureOf, type Texture } from './texture';

// The trend map answers for a case only when it is the same variable and season and the place lies inside
// the painted area (at least half strength, so not out in the fade).
export function caseOnMap(r: CheckResult, view: TrendView): boolean {
  const { place, variable_id, season } = r.case;
  if (place.place_id.startsWith('region:')) return false;
  if (view.layer.variable_id !== variable_id || view.layer.season !== String(season)) return false;
  const cell = cellAt(view.grid, place.lon, place.lat);
  return !!cell && (cell.fade ?? 1) >= 0.5;
}

// A light drawing for a result that has no gridded map: one image laid on the globe. `colour` is its
// main colour (also read by tests); `key` changes when the drawing does.
export interface Overlay { key: string; colour: string; paint: () => { url: string; coordinates: ImageCoordinates } }
const WHITE: Rgb = [244, 244, 240];

function square(lat: number, lon: number, radiusKm: number): ImageCoordinates {
  const dLat = radiusKm / 111, dLon = Math.min(170, radiusKm / (111 * Math.max(0.2, Math.cos(lat * Math.PI / 180))));
  const north = Math.min(MERCATOR_LAT, lat + dLat), south = Math.max(-MERCATOR_LAT, lat - dLat);
  return [[lon - dLon, north], [lon + dLon, north], [lon + dLon, south], [lon - dLon, south]];
}
// A disc that fades to nothing at its edge, optionally in the variable's texture.
function disc([R, G, B]: Rgb, strength: number, texture: Texture | null, extra?: (g: CanvasRenderingContext2D, size: number) => void) {
  const size = 320, canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const g = canvas.getContext('2d')!;
  const fill = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  for (const [stop, a] of [[0, 1], [0.35, 0.9], [0.7, 0.4], [1, 0]]) fill.addColorStop(stop, `rgba(${R},${G},${B},${a * strength})`);
  g.fillStyle = fill;
  g.fillRect(0, 0, size, size);
  applyTexture(g, size, size, texture);
  extra?.(g, size);
  return canvas.toDataURL('image/png');
}

// A climate case outside the map: its own result at its place. The variable's colour and texture when the
// trend is clear (verdict confirmed or refuted), white when it could be chance. The whole planet has no place.
export function caseOverlay(r: CheckResult): Overlay | null {
  const { place, variable_id } = r.case;
  if (place.place_id === 'region:globe') return null;
  const slope = r.sen.slope_per_decade, direction = r.verdict === 'not_proven' || slope === 0 ? 0 : slope > 0 ? 1 : -1;
  const rgb = direction === 0 ? WHITE : coloursOf(variable_id).map(direction > 0 ? 0.92 : 0.08);
  const radiusKm = place.place_id.startsWith('region:') ? 1400 : 320;
  return { key: `case:${place.place_id}:${variable_id}:${direction}`, colour: css(rgb),
    paint: () => ({ url: disc(rgb, direction === 0 ? 0.62 : 0.85, textureOf(variable_id)), coordinates: square(place.lat, place.lon, radiusKm) }) };
}

// A pollution event: a haze at the place (smog brown when the air got dirtier, clear blue when it got
// cleaner, white when the change is not proven) and a dashed ring where the comparison points lie.
const SMOG: Rgb = [196, 112, 47], CLEAN: Rgb = [79, 159, 208], RING_KM = 120, EVENT_KM = 210;
export function eventOverlay(r: EventResult): Overlay {
  const { place } = r.spec;
  const direction = r.verdict !== 'clear_change' || !r.effect ? 0 : r.effect > 0 ? 1 : -1;
  const rgb = direction === 0 ? WHITE : direction > 0 ? SMOG : CLEAN;
  return { key: `event:${place.lat},${place.lon}:${r.spec.compound_id}:${direction}:${r.spec.use_control}`, colour: css(rgb),
    paint: () => ({ coordinates: square(place.lat, place.lon, EVENT_KM), url: disc(rgb, direction === 0 ? 0.55 : 0.85, null, (g, size) => {
      if (!r.spec.use_control) return;
      g.strokeStyle = 'rgba(244,244,240,.9)'; g.lineWidth = 2; g.setLineDash([7, 7]);
      g.beginPath(); g.arc(size / 2, size / 2, size / 2 * RING_KM / EVENT_KM, 0, Math.PI * 2); g.stroke();
    }) }) };
}

// CO₂ mixes around the whole planet, and one source is far too small to see on it. Only the what-if
// atmosphere is drawn: a veil over the planet, stronger the more warming it brings (full strength at 4 °C).
const FULL_VEIL_C = 4;
export function co2Overlay(r: Co2Impact): Overlay | null {
  const warming = r.what_if_warming_c?.central;
  if (warming == null || warming <= 0) return null;
  const t = Math.min(1, warming / FULL_VEIL_C), rgb = coloursOf('global_temp').map(0.5 + t / 2);
  return { key: `co2:${Math.round(t * 100)}`, colour: css(rgb), paint: () => {
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 8;
    const g = canvas.getContext('2d')!;
    g.fillStyle = `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${0.12 + 0.5 * t})`;
    g.fillRect(0, 0, 8, 8);
    return { url: canvas.toDataURL('image/png'), coordinates: [[-180, MERCATOR_LAT], [180, MERCATOR_LAT], [180, -MERCATOR_LAT], [-180, -MERCATOR_LAT]] };
  } };
}
