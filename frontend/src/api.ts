import { z } from 'zod';
import { demoCases } from './data';
import { CaseSpecSchema, ErrorResponseSchema, PlaceSchema, VariableSchema, parseCheckResult } from './schema';
import { matchesPlace } from './places';
import type { CaseSpec, CheckResult, Place, Variable } from './types';

export { demoCases, nearestCase } from './data';
// A new place downloads satellite data and the nearest station's records (up to a minute).
const CHECK_TIMEOUT_MS = 90_000;
// Explicit opt-in; connection failure never silently falls back to synthetic data.
// A deployment built with VITE_DEFAULT_SOURCE=live talks to its backend unless ?source=saved is given.
export const isLive = (new URLSearchParams(window.location.search).get('source') ?? import.meta.env.VITE_DEFAULT_SOURCE) === 'live';

/** An error from the backend: `code` is ErrorBody.code, or 'timeout' / 'network' when no answer came. */
export class ApiError extends Error {
  constructor(message: string, readonly code: string, readonly status?: number) { super(message); this.name = 'ApiError'; }
}

/** The live service could not answer now; a saved snapshot is a fair stand-in. */
export const isTransient = (e: unknown) => e instanceof ApiError && ['busy', 'rate_limited', 'timeout', 'network'].includes(e.code);

export async function request(path: string, init?: RequestInit, signal?: AbortSignal, timeoutMs = 20_000): Promise<unknown> {
  const timeout = AbortSignal.timeout(timeoutMs);
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { ...init, signal: signal ? AbortSignal.any([signal, timeout]) : timeout });
  } catch (e) {
    if (signal?.aborted) throw e;
    if (timeout.aborted) throw new ApiError('The live service took too long to answer.', 'timeout');
    throw new ApiError('Cannot reach the live service.', 'network');
  }
  const data: unknown = await response.json().catch(() => null);
  const error = ErrorResponseSchema.safeParse(data);
  if (!response.ok || error.success) {
    throw error.success ? new ApiError(error.data.error.message, error.data.error.code, response.status)
      : new ApiError(`Request failed (${response.status}). Try again.`, 'http', response.status);
  }
  if (data === null) throw new Error('The server returned no readable JSON.');
  return data;
}

export async function getVariables(signal?: AbortSignal): Promise<Variable[]> {
  if (isLive) {
    const parsed = z.array(VariableSchema).min(1).safeParse(await request('/variables', undefined, signal));
    if (!parsed.success) throw new Error('Invalid or empty variable catalogue returned by the backend.');
    return parsed.data;
  }
  return [...new Map(demoCases.map(item => [item.result.variable.id, item.result.variable])).values()];
}
export const FALLBACK_REGIONS: Place[] = [
  { place_id: 'region:globe', name: 'The whole planet', lat: 0, lon: 0 },
  { place_id: 'region:europe', name: 'Europe', lat: 50, lon: 15 },
  { place_id: 'region:asia', name: 'Asia', lat: 45, lon: 90 },
  { place_id: 'region:africa', name: 'Africa', lat: 5, lon: 20 },
  { place_id: 'region:northamerica', name: 'North America', lat: 45, lon: -100 },
  { place_id: 'region:southamerica', name: 'South America', lat: -15, lon: -60 },
  { place_id: 'region:oceania', name: 'Oceania', lat: -25, lon: 135 },
  { place_id: 'region:arctic', name: 'The Arctic', lat: 80, lon: 0 },
];

export async function getRegions(signal?: AbortSignal): Promise<Place[]> {
  if (!isLive) return FALLBACK_REGIONS;
  const parsed = z.array(PlaceSchema).min(1).safeParse(await request('/regions', undefined, signal));
  if (!parsed.success) throw new Error('Invalid region list returned by the backend.');
  return parsed.data;
}

export async function findPlaces(query: string, signal?: AbortSignal, options?: { includeRegions?: boolean }): Promise<Place[]> {
  const includeRegions = options?.includeRegions ?? false;
  if (isLive) {
    const suffix = includeRegions ? '' : '&include_regions=false';
    const parsed = z.array(PlaceSchema).safeParse(await request(`/places?q=${encodeURIComponent(query)}${suffix}`, undefined, signal));
    if (!parsed.success) throw new Error('Invalid place search response returned by the backend.');
    return parsed.data;
  }
  const places = [...new Map(demoCases.map(item => [item.result.case.place.place_id, item.result.case.place])).values()]
    .filter(place => includeRegions || !place.place_id.startsWith('region:'));
  return places.filter(place => matchesPlace(place, query));
}
export async function runCheck(spec: CaseSpec, _demoId: string, signal?: AbortSignal): Promise<CheckResult> {
  if (isLive) {
    const result = await request('/check', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(spec),
    }, signal, CHECK_TIMEOUT_MS);
    return parseCheckResult(result);
  }
  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  const fixture = demoCases.find(item => {
    const original = item.result.case;
    return original.claim_text === spec.claim_text && original.variable_id === spec.variable_id && original.place.place_id === spec.place.place_id &&
      original.season === spec.season && original.start_year === spec.start_year &&
      original.end_year === spec.end_year && original.claim_direction === spec.claim_direction;
  });
  if (!fixture) throw new Error('No saved backend response matches these parameters. Open one of the saved cases. Custom calculations require the calculation API.');
  return structuredClone(fixture.result);
}

const ParsedClaimSchema = z.object({
  spec: CaseSpecSchema, place_found: z.boolean(), place_query: z.string().nullable().optional(), notes: z.array(z.string()), model: z.string(),
}).strict();
export type ParsedClaim = z.infer<typeof ParsedClaimSchema>;

/** Free text -> check parameters (POST /api/parse-claim). Nothing is checked; the user confirms the fields first. */
export async function parseClaim(text: string, signal?: AbortSignal): Promise<ParsedClaim> {
  if (!isLive) throw new ApiError('Reading a claim needs the backend. Open a saved case instead.', 'offline');
  const parsed = ParsedClaimSchema.safeParse(await request('/parse-claim', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }),
  }, signal, 30_000));
  if (!parsed.success) throw new Error('Invalid claim reading returned by the backend.');
  return parsed.data;
}

const CaseListSchema =z.array(z.object({ id: z.string().min(1), claim_text: z.string(), place: z.string(), variable_id: z.string(), verdict: z.string() }));
export type CaseItem = { id: string; claim_text: string };

// The case grid: GET /api/cases in live mode, the saved responses otherwise.
export async function getCases(signal?: AbortSignal): Promise<CaseItem[]> {
  if (!isLive) return demoCases.map(item => ({ id: item.id, claim_text: item.result.case.claim_text }));
  const parsed = CaseListSchema.safeParse(await request('/cases', undefined, signal));
  if (!parsed.success) throw new Error('Invalid case list returned by the backend.');
  return parsed.data.map(({ id, claim_text }) => ({ id, claim_text }));
}
export async function getCase(id: string, signal?: AbortSignal): Promise<CheckResult> {
  if (isLive) return parseCheckResult(await request(`/cases/${encodeURIComponent(id)}`, undefined, signal));
  const saved = demoCases.find(item => item.id === id);
  if (!saved) throw new Error(`Unknown saved case '${id}'.`);
  return structuredClone(saved.result);
}
