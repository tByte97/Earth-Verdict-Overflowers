// One drawing style per kind of climate variable, so the map reads at a glance: temperature is an even glow,
// precipitation falls in slanted streaks, snow lies in dots, soil in ground dashes, sunlight in sparks and
// evaporation in rising waves. Texture only: it thins the colour between the marks and never changes it.
export type Texture = 'rain' | 'snow' | 'soil' | 'sun' | 'vapour';
const textures: Record<string, Texture> = {
  precip: 'rain', precip_gpm: 'rain', snow_depth: 'snow', soil_moisture: 'soil', sunlight: 'sun', evapotranspiration: 'vapour',
};
export const textureOf = (variableId: string): Texture | null => textures[variableId] ?? null;
export const textureWords: Record<Texture, string> = {
  rain: 'streaks = precipitation', snow: 'dots = snow', soil: 'dashes = soil', sun: 'sparks = sunlight', vapour: 'waves = evaporation',
};

// How much colour stays between the marks.
const BETWEEN = 0.42;
const tiles = new Map<Texture, HTMLCanvasElement>();
function tile(texture: Texture) {
  const cached = tiles.get(texture);
  if (cached) return cached;
  const [w, h] = { rain: [12, 12], snow: [14, 14], soil: [18, 9], sun: [16, 16], vapour: [12, 18] }[texture];
  const canvas = document.createElement('canvas');
  canvas.width = w; canvas.height = h;
  const g = canvas.getContext('2d')!;
  g.fillStyle = `rgba(0,0,0,${BETWEEN})`;
  g.fillRect(0, 0, w, h);
  g.strokeStyle = g.fillStyle = '#000';
  g.lineCap = 'round';
  if (texture === 'rain') {
    g.lineWidth = 2;
    // Two segments so the streak joins across tile edges.
    for (const dx of [0, w]) { g.beginPath(); g.moveTo(dx + 4, -2); g.lineTo(dx - 4, h + 2); g.stroke(); }
  } else if (texture === 'snow') {
    for (const [x, y, r] of [[3.5, 3.5, 2.2], [10.5, 10.5, 1.8]]) { g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.fill(); }
  } else if (texture === 'soil') {
    g.lineWidth = 2;
    g.beginPath(); g.moveTo(2, 2.5); g.lineTo(9, 2.5); g.moveTo(11, 6.5); g.lineTo(18, 6.5); g.moveTo(0, 6.5); g.lineTo(0.5, 6.5); g.stroke();
  } else if (texture === 'sun') {
    g.lineWidth = 1.6;
    g.beginPath(); g.moveTo(8, 3.5); g.lineTo(8, 12.5); g.moveTo(3.5, 8); g.lineTo(12.5, 8); g.stroke();
  } else {
    g.lineWidth = 1.8;
    g.beginPath(); g.moveTo(6, 0);
    for (let y = 0; y <= h; y += 1) g.lineTo(6 + 2.6 * Math.sin(y / h * Math.PI * 2), y);
    g.stroke();
  }
  tiles.set(texture, canvas);
  return canvas;
}

// Keeps the painted colour where the pattern is dark and thins it elsewhere.
export function applyTexture(ctx: CanvasRenderingContext2D, width: number, height: number, texture: Texture | null) {
  if (!texture) return;
  const pattern = ctx.createPattern(tile(texture), 'repeat');
  if (!pattern) return;
  ctx.save();
  ctx.globalCompositeOperation = 'destination-in';
  ctx.fillStyle = pattern;
  ctx.fillRect(0, 0, width, height);
  ctx.restore();
}
