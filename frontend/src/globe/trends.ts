/// <reference types="vite/client" />
import { z } from 'zod';
import { isLive } from '../api';
import type { CaseSpec } from '../types';

// Temporary: the layer files do not name their variable or period yet, so this repeats the
// variable → POWER parameter mapping of `/api/grid` in backend/app/main.py. Drop it once the
// layer metadata carries `variable_id` and the period.
const LAYER_PARAM: Record<string, string> = { air_temp: 'T2M', precip: 'PRECTOTCORR' };

const CellSchema = z.object({
  type: z.literal('Feature'),
  geometry: z.object({ type: z.literal('Polygon'), coordinates: z.array(z.array(z.tuple([z.number(), z.number()]))) }),
  properties: z.object({ lat: z.number(), lon: z.number(), slope_per_decade: z.number(), p: z.number(), significant_fdr: z.boolean() }).passthrough(),
});
const TrendLayerSchema = z.object({
  type: z.literal('FeatureCollection'),
  param: z.string(), season: z.string(), units_per_decade: z.string(), q: z.number(),
  start_year: z.number().int().optional(), end_year: z.number().int().optional(),
  features: z.array(CellSchema).min(1),
});
export type TrendLayer = z.infer<typeof TrendLayerSchema>;
export type TrendCell = TrendLayer['features'][number]['properties'];

// Saved mode reads the team's layer files directly, like data.ts does for the cases; each file is its own lazy chunk.
const savedLayers = import.meta.glob<string>('../../../data/layers/trends_*.geojson', { query: '?raw', import: 'default' });

// Resolves to null whenever no layer exists for this variable and season: nothing is substituted.
export async function loadTrendLayer(variableId: string, season: CaseSpec['season'], signal: AbortSignal): Promise<TrendLayer | null> {
  const param = LAYER_PARAM[variableId];
  if (!param || typeof season !== 'string') return null;
  let raw: unknown;
  if (isLive) {
    const response = await fetch(`/api/grid?${new URLSearchParams({ variable_id: variableId, season })}`, { signal });
    if (!response.ok) return null;
    raw = await response.json();
  } else {
    const file = savedLayers[`../../../data/layers/trends_${param}_${season}.geojson`];
    if (!file) return null;
    raw = JSON.parse(await file());
  }
  const layer = TrendLayerSchema.safeParse(raw);
  return layer.success && layer.data.param === param && layer.data.season === season ? layer.data : null;
}
