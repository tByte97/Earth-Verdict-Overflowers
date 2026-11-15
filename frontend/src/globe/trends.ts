/// <reference types="vite/client" />
import { z } from 'zod';
import { isLive, request } from '../api';

const CellSchema = z.object({
  type: z.literal('Feature'),
  // `halo` marks a cell outside the tested area: drawn so the map fades out over real data, never counted.
  properties: z.object({ lat: z.number(), lon: z.number(), slope_per_decade: z.number(), p: z.number(), significant_fdr: z.boolean(), halo: z.boolean().optional(), fade: z.number().min(0).max(1).optional() }).passthrough(),
}).passthrough();
const PairEndSchema = z.object({ lat: z.number(), lon: z.number(), slope_per_decade: z.number(), p: z.number() });
const LayerEntrySchema = z.object({
  variable_id: z.string(), season: z.string(), start_year: z.number().int(), end_year: z.number().int(), units_per_decade: z.string(),
});
const TrendLayerSchema = LayerEntrySchema.extend({
  type: z.literal('FeatureCollection'),
  q: z.number(),
  pair: z.object({ a: PairEndSchema, b: PairEndSchema, distance_km: z.number(), significance: z.enum(['fdr', 'raw']) }).nullable(),
  // Cell counts arrive with the layer index; older layer files do not carry them.
  n_cells: z.number().int().optional(), n_significant_fdr: z.number().int().optional(),
  // Fade distance outside Ukraine's border in km (or legacy halo_cells ring count).
  fade_km: z.number().positive().optional(),
  halo_cells: z.number().int().nonnegative().optional(),
  features: z.array(CellSchema).min(1),
}).passthrough();

export type LayerEntry = z.infer<typeof LayerEntrySchema>;
export type TrendLayer = z.infer<typeof TrendLayerSchema>;
export type TrendCell = TrendLayer['features'][number]['properties'];
export type PairEnd = z.infer<typeof PairEndSchema>;

// Saved mode reads the team's layer files directly, like data.ts does for the cases. Each file is its own lazy chunk,
// and the files themselves say which variable, season and period they hold.
const savedFiles = import.meta.glob<string>('../../../data/layers/trends_*.geojson', { query: '?raw', import: 'default' });
let savedLayers: Promise<TrendLayer[]> | undefined;
const loadSavedLayers = () => savedLayers ??= Promise.all(Object.values(savedFiles).map(async file => TrendLayerSchema.safeParse(JSON.parse(await file()))))
  .then(results => results.flatMap(result => (result.success ? [result.data] : [])).sort((a, b) => a.variable_id.localeCompare(b.variable_id)));

const entryOf = ({ variable_id, season, start_year, end_year, units_per_decade }: LayerEntry): LayerEntry => ({ variable_id, season, start_year, end_year, units_per_decade });

// The layers that exist. Null when the backend has no index yet: then only the current case's layer is shown.
export async function loadLayerIndex(signal: AbortSignal): Promise<LayerEntry[] | null> {
  if (!isLive) return (await loadSavedLayers()).map(entryOf);
  const response = await fetch('/api/grid/index', { signal: AbortSignal.any([signal, AbortSignal.timeout(20_000)]) });
  if (response.status === 404) return null;
  const parsed = z.array(LayerEntrySchema).safeParse(await response.json().catch(() => null));
  if (!response.ok || !parsed.success) throw new Error('Invalid trend layer index returned by the backend.');
  return parsed.data.map(entryOf);
}

// Resolves to null when no layer exists for this variable and season: nothing is substituted.
export async function loadTrendLayer(variableId: string, season: string, signal: AbortSignal): Promise<TrendLayer | null> {
  const matches = (layer: TrendLayer) => layer.variable_id === variableId && layer.season === season;
  if (!isLive) return (await loadSavedLayers()).find(matches) ?? null;
  const parsed = TrendLayerSchema.safeParse(await request(`/grid?${new URLSearchParams({ variable_id: variableId, season })}`, undefined, signal));
  if (!parsed.success) throw new Error('Invalid trend layer returned by the backend.');
  return matches(parsed.data) ? parsed.data : null;
}
