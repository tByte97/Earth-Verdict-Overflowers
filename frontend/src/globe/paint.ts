import type { TrendCell } from './trends';
import { niceStep, type Ramp } from '../colour';
import { applyTexture, type Texture } from './texture';

// Display scale only: the 95th percentile of |slope| rounded up to a nice step, so one extreme cell does not wash out the map.
export function colourLimit(cells: TrendCell[]) {
  const sorted = cells.map(cell => Math.abs(cell.slope_per_decade)).sort((a, b) => a - b);
  return niceStep(sorted[Math.floor(0.95 * (sorted.length - 1))] || 1);
}

// The layer's cells sit on a regular lat/lon grid; its spacing is read from the cell centres.
export interface Grid<T = TrendCell> { lat0: number; lon0: number; dlat: number; dlon: number; nlat: number; nlon: number; cells: (T | undefined)[] }
const step = (values: number[]) => {
  const sorted = [...new Set(values)].sort((a, b) => a - b);
  return { first: sorted[0], step: sorted.length > 1 ? sorted[1] - sorted[0] : 1, count: sorted.length > 1 ? Math.round((sorted.at(-1)! - sorted[0]) / (sorted[1] - sorted[0])) + 1 : 1 };
};
export function gridOf<T extends { lat: number; lon: number }>(cells: T[]): Grid<T> {
  const lat = step(cells.map(cell => cell.lat)), lon = step(cells.map(cell => cell.lon));
  const grid: Grid<T> = { lat0: lat.first, lon0: lon.first, dlat: lat.step, dlon: lon.step, nlat: lat.count, nlon: lon.count, cells: [] };
  for (const cell of cells) grid.cells[Math.round((cell.lat - grid.lat0) / grid.dlat) * grid.nlon + Math.round((cell.lon - grid.lon0) / grid.dlon)] = cell;
  return grid;
}
export function cellAt<T>(grid: Grid<T>, lon: number, lat: number) {
  const r = Math.round((lat - grid.lat0) / grid.dlat), c = Math.round((lon - grid.lon0) / grid.dlon);
  return r < 0 || c < 0 || r >= grid.nlat || c >= grid.nlon ? undefined : grid.cells[r * grid.nlon + c];
}

// Web Mercator helpers: the image is painted in Mercator rows so it lines up with the flat map.
const mx = (lon: number) => (lon + 180) / 360;
const my = (lat: number) => (1 - Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360)) / Math.PI) / 2;
const latOfY = (y: number) => Math.atan(Math.sinh(Math.PI * (1 - 2 * y))) * 180 / Math.PI;

// Web Mercator stops at this latitude; beyond it there is no map to draw on.
export const MERCATOR_LAT = 85.0511;

// An equirectangular (EPSG:4326) world image re-laid in Mercator rows, so an image source lines up with the tiles.
export function mercatorWorld(image: HTMLImageElement) {
  const W = image.naturalWidth, H = W;
  const canvas = document.createElement('canvas');
  canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext('2d')!;
  const top = my(MERCATOR_LAT), bottom = my(-MERCATOR_LAT);
  for (let py = 0; py < H; py++) {
    const lat = latOfY(top + (py + 0.5) / H * (bottom - top));
    ctx.drawImage(image, 0, (90 - lat) / 180 * image.naturalHeight, W, 1, 0, py, W, 1);
  }
  return canvas.toDataURL('image/jpeg', 0.9);
}

const TEXTURE_SCALE = 3;
export type ImageCoordinates = [[number, number], [number, number], [number, number], [number, number]];

// Pure rendering: per-cell value in [-1, 1] and opacity → a smooth image. The bilinear blend is for
// colour only; tooltips always read the exact cell. Colour fades next to missing cells; the outer
// shape and soft border come from the per-cell `fade` weight in `alpha`.
export function paintGrid<T>(grid: Grid<T>, value: (cell: T) => number, alpha: (cell: T) => number, colour: Ramp, texture: Texture | null = null) {
  const { lat0, lon0, dlat, dlon, nlat, nlon, cells } = grid;
  // Pad by one cell on every side so outermost cells fade next to empty space like interior edges.
  const west = lon0 - dlon, east = lon0 + nlon * dlon;
  const south = lat0 - dlat, north = lat0 + nlat * dlat;
  const W = (nlon + 1) * 8, yN = my(north), yS = my(south);
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
      const edge = Math.min(1, Math.max(0, (sw - 0.2) / 0.4));
      if (!edge) continue;
      const [R, G, B] = colour(sv / sw);
      d[o] = R; d[o + 1] = G; d[o + 2] = B; d[o + 3] = Math.round(255 * edge * sa / sw);
    }
  }
  ctx.putImageData(img, 0, 0);
  const coordinates: ImageCoordinates = [[west, north], [east, north], [east, south], [west, south]];
  if (!texture) return { url: canvas.toDataURL('image/png'), coordinates };
  // The texture is drawn on an enlarged copy, so its marks stay fine when the map is zoomed in.
  const fine = document.createElement('canvas');
  fine.width = W * TEXTURE_SCALE; fine.height = H * TEXTURE_SCALE;
  const fctx = fine.getContext('2d')!;
  fctx.drawImage(canvas, 0, 0, fine.width, fine.height);
  applyTexture(fctx, fine.width, fine.height, texture);
  return { url: fine.toDataURL('image/png'), coordinates };
}
