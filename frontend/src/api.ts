import { demoCases } from './data';
import type { CaseSpec, CheckResult, Place, Variable } from './types';

export { demoCases } from './data';
// Explicit opt-in; connection failure never silently falls back to synthetic data.
export const isLive = new URLSearchParams(window.location.search).get('source') === 'live';

async function request<T>(path: string, init?: RequestInit, signal?: AbortSignal): Promise<T> {
  const timeout = AbortSignal.timeout(20_000);
  const response = await fetch(`/api${path}`, { ...init, signal: signal ? AbortSignal.any([signal, timeout]) : timeout });
  const data = await response.json().catch(() => null);
  if (!response.ok || data?.error) throw new Error(data?.error?.message || `Request failed (${response.status}). Try again.`);
  if (data === null) throw new Error('The server returned no readable JSON.');
  return data as T;
}

export async function getVariables(signal?: AbortSignal): Promise<Variable[]> {
  if (isLive) return request('/variables', undefined, signal);
  return [...new Map(demoCases.map(item => [item.result.variable.id, item.result.variable])).values()];
}
export async function findPlaces(query: string, signal?: AbortSignal): Promise<Place[]> {
  if (isLive) return request(`/places?q=${encodeURIComponent(query)}`, undefined, signal);
  const places = [...new Map(demoCases.map(item => [item.result.case.place.place_id, item.result.case.place])).values()];
  return places.filter(place => `${place.name} ${place.place_id} ${place.place_id.endsWith('lviv') ? 'Lviv Львів' : 'Kyiv Київ'}`.toLowerCase().includes(query.trim().toLowerCase()));
}
export async function runCheck(spec: CaseSpec, demoId: string, signal?: AbortSignal): Promise<CheckResult> {
  if (isLive) {
    const result = await request<CheckResult>('/check', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(spec),
    }, signal);
    if (!validResult(result)) {
      throw new Error('The response does not match CheckResult. Please check the backend contract.');
    }
    return result;
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

// Guard required display structure so an incomplete response produces an error, not a blank page.
function validResult(r: CheckResult) {
  if (!r || !['confirmed', 'refuted', 'not_proven'].includes(r.verdict) ||
    !r.case?.place || typeof r.case.claim_text !== 'string' ||
    !Number.isInteger(r.case.start_year) || !Number.isInteger(r.case.end_year) ||
    !r.variable?.units || !r.sen || !r.mk || !r.ols || !r.robustness_summary ||
    !Array.isArray(r.series) || !Array.isArray(r.robustness) || !Array.isArray(r.provenance)) return false;
  const metric = (n: unknown) => n === null || typeof n === 'number' && Number.isFinite(n);
  if (![r.sen.slope_per_decade, r.mk.p, r.ols.p, r.years_to_wait].every(metric)) return false;
  if (r.witness !== null && (!r.witness?.station || !r.witness.sen || !r.witness.mk ||
    !Array.isArray(r.witness.series) || !['agree', 'one_source', 'disagree', 'no_station'].includes(r.witness.agreement))) return false;
  return r.series.every(row => row && Number.isInteger(row.year) && metric(row.value)) &&
    r.robustness.every(row => row && Number.isInteger(row.start_year) && Number.isInteger(row.end_year) && metric(row.p) && metric(row.slope_per_decade) && typeof row.significant === 'boolean') &&
    r.provenance.every(source => source && typeof source.url === 'string');
}
