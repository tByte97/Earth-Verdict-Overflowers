import type { CaseSpec } from './types';

// Shareable view state in the URL hash: `#case={id}` for a saved case, or
// `#v={variable}&s={season}&p={start}-{end}&pt={lon},{lat}` for a picked spot.
export type ViewState =
  | { kind: 'case'; id: string }
  | { kind: 'spot'; variable: string; season: CaseSpec['season']; start: number; end: number; lon: number; lat: number };

const SEASONS = new Set(['year', 'DJF', 'MAM', 'JJA', 'SON']);

export function parseHash(hash: string): ViewState | null {
  const params = new URLSearchParams(hash.replace(/^#/, ''));
  const id = params.get('case');
  if (id) return { kind: 'case', id };
  const variable = params.get('v'), season = params.get('s');
  const period = /^(\d{4})-(\d{4})$/.exec(params.get('p') ?? '');
  const point = (params.get('pt') ?? '').split(',').map(Number);
  if (!variable || !season || !period || point.length !== 2 || !point.every(Number.isFinite)) return null;
  const month = /^\d+$/.test(season) ? Number(season) : NaN;
  if (!SEASONS.has(season) && !(month >= 1 && month <= 12)) return null;
  const [lon, lat] = point;
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
  return { kind: 'spot', variable, season: SEASONS.has(season) ? season as CaseSpec['season'] : month, start: Number(period[1]), end: Number(period[2]), lon, lat };
}

export function formatHash(state: ViewState | null): string {
  if (!state) return '';
  if (state.kind === 'case') return `#${new URLSearchParams({ case: state.id })}`;
  return `#${new URLSearchParams({ v: state.variable, s: String(state.season), p: `${state.start}-${state.end}`, pt: `${state.lon},${state.lat}` })}`;
}

// Replaces only the hash, so `?source=` and `?mode=` stay as they are.
export function writeHash(state: ViewState | null) {
  const url = new URL(window.location.href);
  url.hash = formatHash(state);
  window.history.replaceState(null, '', url);
}
