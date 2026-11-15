import type maplibregl from 'maplibre-gl';
import type { CheckResult, Place } from '../types';

export type Box = [west: number, south: number, east: number, north: number];
// Where a flight ends: the whole planet, or a box fitted to the stage.
export type View = { kind: 'globe' } | { kind: 'box'; box: Box };
// A flight request from the app; a new `key` starts a new flight.
export type Destination = { key: number; title: string; view: View };

export const GLOBE_VIEW = { center: [20, 30] as [number, number], zoom: 1.4 };
const ORBIT_ZOOM = 2, MAX_ZOOM = 7;
// A display choice, not data: the smallest box a flight frames around a place, in degrees from it.
const MIN_HALF_BOX = { lat: 3, lon: 5 };

// The contract has no case box: regions show the whole planet, other places get a box
// around the place and its ground station.
export function placeView(place: Place, station?: { lat: number; lon: number } | null): View {
  if (place.place_id.startsWith('region:')) return { kind: 'globe' };
  const lats = [place.lat, station?.lat ?? place.lat], lons = [place.lon, station?.lon ?? place.lon];
  return { kind: 'box', box: [
    Math.min(...lons, place.lon - MIN_HALF_BOX.lon), Math.max(Math.min(...lats, place.lat - MIN_HALF_BOX.lat), -85),
    Math.max(...lons, place.lon + MIN_HALF_BOX.lon), Math.min(Math.max(...lats, place.lat + MIN_HALF_BOX.lat), 85),
  ] };
}
export const caseView = (r: CheckResult) => placeView(r.case.place, r.witness?.station);

// Web Mercator helpers in 0..1 world units.
const mx = (lon: number) => (lon + 180) / 360;
const my = (lat: number) => (1 - Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360)) / Math.PI) / 2;
const latOfY = (y: number) => Math.atan(Math.sinh(Math.PI * (1 - 2 * y))) * 180 / Math.PI;

// Fits a box into a stage of width × height, leaving room for the legend (top right) and the stage title (bottom).
export function boxCamera([w, s, e, n]: Box, width: number, height: number) {
  const pad = width < 700 ? { top: 70, bottom: 100, left: 20, right: 20 } : { top: 80, bottom: 140, left: 50, right: 260 };
  const dx = mx(e) - mx(w), dy = my(s) - my(n);
  const zoom = Math.min(MAX_ZOOM, Math.log2(Math.min((width - pad.left - pad.right) / (dx * 512), (height - pad.top - pad.bottom) / (dy * 512))));
  const world = 512 * 2 ** zoom;
  const cx = (mx(w) + mx(e)) / 2 + (pad.right - pad.left) / 2 / world;
  const cy = (my(n) + my(s)) / 2 + (pad.bottom - pad.top) / 2 / world;
  return { center: [cx * 360 - 180, latOfY(cy)] as [number, number], zoom };
}

const easeIn = (t: number) => t ** 3;
const easeOut = (t: number) => 1 - (1 - t) ** 3;
const easeInOut = (t: number) => (t < 0.5 ? 4 * t ** 3 : 1 - (2 - 2 * t) ** 3 / 2);
export const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

// Camera path to a new case: rise to orbit, turn the planet under it, then settle on the view.
// `stillWanted` turns false when a newer flight, a view button or the user takes over the camera.
export async function flyToView(map: maplibregl.Map, view: View, stillWanted: () => boolean) {
  const { clientWidth, clientHeight } = map.getContainer();
  const target = view.kind === 'globe' ? GLOBE_VIEW : boxCamera(view.box, clientWidth, clientHeight);
  if (reducedMotion()) { map.jumpTo({ ...target, pitch: 0, bearing: 0 }); return; }
  // Listen after starting: easeTo stops the previous animation, whose moveend fires synchronously.
  const leg = (options: maplibregl.EaseToOptions) => new Promise<void>(resolve => {
    map.easeTo({ ...options, essential: true });
    map.once('moveend', () => resolve());
  });
  if (map.getZoom() > ORBIT_ZOOM + 0.4) await leg({ zoom: ORBIT_ZOOM, pitch: 0, bearing: 0, duration: 1100, easing: easeIn });
  if (!stillWanted()) return;
  await leg({ center: target.center, zoom: Math.min(ORBIT_ZOOM, target.zoom), duration: 1000, easing: easeInOut });
  if (!stillWanted()) return;
  await leg({ ...target, duration: 1600, easing: easeOut });
}
