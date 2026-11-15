import type { TrendCell } from './trends';

// Colour: OKLab interpolation keeps diverging ramps perceptually even on both sides of zero.
type Rgb = [number, number, number];
const toLin = (c: number) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const fromLin = (c: number) => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);
function hexToLab(hex: string): Rgb {
  const [r, g, b] = [1, 3, 5].map(i => toLin(parseInt(hex.slice(i, i + 2), 16) / 255));
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s];
}
function labToRgb([L, a, b]: Rgb): Rgb {
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  return [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s]
    .map(c => Math.round(255 * Math.min(1, Math.max(0, fromLin(c))))) as Rgb;
}
export type Ramp = (t: number) => Rgb;
export function ramp(stops: string[]): Ramp {
  const labs = stops.map(hexToLab);
  return t => {
    t = Math.min(1, Math.max(0, t)) * (labs.length - 1);
    const i = Math.min(labs.length - 2, Math.floor(t)), f = t - i;
    return labToRgb(labs[i].map((v, k) => v + (labs[i + 1][k] - v) * f) as Rgb);
  };
}
const css = ([r, g, b]: Rgb) => `rgb(${r},${g},${b})`;
export const gradient = (fn: Ramp, n = 12) => `linear-gradient(90deg, ${Array.from({ length: n }, (_, i) => css(fn(i / (n - 1)))).join(',')})`;

// Display scale only: the 95th percentile of |slope| rounded up to a nice step, so one extreme cell does not wash out the map.
export function niceLimit(x: number) {
  const e = 10 ** Math.floor(Math.log10(x)), f = x / e;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * e;
}
export function colourLimit(cells: TrendCell[]) {
  const sorted = cells.map(cell => Math.abs(cell.slope_per_decade)).sort((a, b) => a - b);
  return niceLimit(sorted[Math.floor(0.95 * (sorted.length - 1))] || 1);
}

// The layer's cells sit on a regular lat/lon grid; its spacing is read from the cell centres.
export interface Grid { lat0: number; lon0: number; dlat: number; dlon: number; nlat: number; nlon: number; cells: (TrendCell | undefined)[] }
const step = (values: number[]) => {
  const sorted = [...new Set(values)].sort((a, b) => a - b);
  return { first: sorted[0], step: sorted.length > 1 ? sorted[1] - sorted[0] : 1, count: sorted.length > 1 ? Math.round((sorted.at(-1)! - sorted[0]) / (sorted[1] - sorted[0])) + 1 : 1 };
};
export function gridOf(cells: TrendCell[]): Grid {
  const lat = step(cells.map(cell => cell.lat)), lon = step(cells.map(cell => cell.lon));
  const grid: Grid = { lat0: lat.first, lon0: lon.first, dlat: lat.step, dlon: lon.step, nlat: lat.count, nlon: lon.count, cells: [] };
  for (const cell of cells) grid.cells[Math.round((cell.lat - grid.lat0) / grid.dlat) * grid.nlon + Math.round((cell.lon - grid.lon0) / grid.dlon)] = cell;
  return grid;
}
export function cellAt(grid: Grid, lon: number, lat: number) {
  const r = Math.round((lat - grid.lat0) / grid.dlat), c = Math.round((lon - grid.lon0) / grid.dlon);
  return r < 0 || c < 0 || r >= grid.nlat || c >= grid.nlon ? undefined : grid.cells[r * grid.nlon + c];
}

// Web Mercator helpers: the image is painted in Mercator rows so it lines up with the flat map.
const mx = (lon: number) => (lon + 180) / 360;
const my = (lat: number) => (1 - Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360)) / Math.PI) / 2;
const latOfY = (y: number) => Math.atan(Math.sinh(Math.PI * (1 - 2 * y))) * 180 / Math.PI;
const smooth = (t: number) => (t = Math.min(1, Math.max(0, t))) * t * (3 - 2 * t);

export type ImageCoordinates = [[number, number], [number, number], [number, number], [number, number]];

// Pure rendering: per-cell value in [-1, 1] and opacity → a smooth image. The bilinear blend is for
// colour only; tooltips always read the exact cell. Colour fades next to missing cells and over the
// last 3 cells at the data edge.
export function paintGrid(grid: Grid, value: (cell: TrendCell) => number, alpha: (cell: TrendCell) => number, colour: Ramp) {
  const { lat0, lon0, dlat, dlon, nlat, nlon, cells } = grid;
  const west = lon0 - dlon / 2, east = lon0 + (nlon - 0.5) * dlon;
  const south = lat0 - dlat / 2, north = lat0 + (nlat - 0.5) * dlat;
  const W = nlon * 8, yN = my(north), yS = my(south);
  const H = Math.max(1, Math.round(W * (yS - yN) / (mx(east) - mx(west))));
  const canvas = document.createElement('canvas');
  canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext('2d')!, img = ctx.createImageData(W, H), d = img.data;
  for (let py = 0; py < H; py++) {
    const fr = (latOfY(yN + (py + 0.5) / H * (yS - yN)) - lat0) / dlat;
    const r0 = Math.floor(fr), tr = fr - r0;
    for (let px = 0; px < W; px++) {
      const fc = (west + (px + 0.5) / W * (east - west) - lon0) / dlon;
      const c0 = Math.floor(fc), tc = fc - c0;
      let sw = 0, sv = 0, sa = 0;
      for (let k = 0; k < 4; k++) {
        const r = r0 + (k >> 1), c = c0 + (k & 1);
        if (r < 0 || c < 0 || r >= nlat || c >= nlon) continue;
        const cell = cells[r * nlon + c];
        if (!cell) continue;
        const w = (k >> 1 ? tr : 1 - tr) * (k & 1 ? tc : 1 - tc);
        sw += w; sv += w * value(cell); sa += w * alpha(cell);
      }
      const o = (py * W + px) * 4;
      const border = Math.min(fr + 0.5, nlat - 0.5 - fr, fc + 0.5, nlon - 0.5 - fc) / 3;
      const edge = Math.min(1, Math.max(0, (sw - 0.2) / 0.4)) * smooth(border);
      if (!edge) continue;
      const [R, G, B] = colour(sv / sw);
      d[o] = R; d[o + 1] = G; d[o + 2] = B; d[o + 3] = Math.round(255 * edge * sa / sw);
    }
  }
  ctx.putImageData(img, 0, 0);
  const coordinates: ImageCoordinates = [[west, north], [east, north], [east, south], [west, south]];
  return { url: canvas.toDataURL('image/png'), coordinates };
}
