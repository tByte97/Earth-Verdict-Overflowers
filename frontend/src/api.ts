import { z } from 'zod';
import { demoCases } from './data';
import { ErrorResponseSchema, PlaceSchema, VariableSchema, parseCheckResult } from './schema';
import { matchesPlace } from './places';
import type { CaseSpec, CheckResult, Place, Variable } from './types';

export { demoCases } from './data';
// Explicit opt-in; connection failure never silently falls back to synthetic data.
export const isLive = new URLSearchParams(window.location.search).get('source') === 'live';

async function request(path: string, init?: RequestInit, signal?: AbortSignal): Promise<unknown> {
  const timeout = AbortSignal.timeout(20_000);
  const response = await fetch(`/api${path}`, { ...init, signal: signal ? AbortSignal.any([signal, timeout]) : timeout });
  const data: unknown = await response.json().catch(() => null);
  const error = ErrorResponseSchema.safeParse(data);
  if (!response.ok || error.success) throw new Error(error.success ? error.data.error.message : `Request failed (${response.status}). Try again.`);
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
export async function findPlaces(query: string, signal?: AbortSignal): Promise<Place[]> {
  if (isLive) {
    const parsed = z.array(PlaceSchema).safeParse(await request(`/places?q=${encodeURIComponent(query)}`, undefined, signal));
    if (!parsed.success) throw new Error('Invalid place search response returned by the backend.');
    return parsed.data;
  }
  const places = [...new Map(demoCases.map(item => [item.result.case.place.place_id, item.result.case.place])).values()];
  return places.filter(place => matchesPlace(place, query));
}
export async function runCheck(spec: CaseSpec, _demoId: string, signal?: AbortSignal): Promise<CheckResult> {
  if (isLive) {
    const result = await request('/check', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(spec),
    }, signal);
    return parseCheckResult(result);
  }
  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  const fixture = demoCases.find(item => {
    const original = item.result.case;
    return original.claim_text === spec.claim_text && original.variable_id === spec.variable_id && original.place.place_id === spec.place.place_id &&
      original.season === spec.season && original.start_year === spec.start_year &&
      original.end_year === spec.end_year && original.claim_direction === spec.claim_direction;
  });
  if (!fixture) throw new Error('No saved backend response matches these parameters. Choose one of the three saved cases. Custom calculations require the calculation API.');
  return structuredClone(fixture.result);
}
