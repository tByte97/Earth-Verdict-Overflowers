import type { DemoCase } from './types';
import { parseCheckResult } from './schema';

// Every saved case in data/cases is bundled into the build; values are never copied or recalculated.
// mock.json is an alias of the Kyiv heat case and is skipped.
const files = import.meta.glob('../../data/cases/*.json', { eager: true, import: 'default' }) as Record<string, unknown>;
// The six cases of the first grid keep their order; the others follow alphabetically.
const FIRST = ['kyiv-summer-heat', 'lviv-drier', 'kyiv-winter-snow', 'kyiv-colder', 'kyiv-summer-rain', 'global-warming-stopped'];
const VERDICT_WORD = { confirmed: 'Confirmed', refuted: 'Refuted', not_proven: 'Not proven' } as const;

const rank = (id: string) => { const i = FIRST.indexOf(id); return i < 0 ? FIRST.length : i; };

export const demoCases: DemoCase[] = Object.entries(files)
  .map(([path, json]) => [path.split('/').pop()!.replace(/\.json$/, ''), json] as const)
  .filter(([id]) => id !== 'mock')
  .sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b))
  .map(([id, json]) => {
    const result = parseCheckResult(json);
    return { id, label: `${result.case.place.name.split(',')[0]} · ${result.case.claim_text} · ${VERDICT_WORD[result.verdict]}`, result };
  });

function km(a: { lat: number; lon: number }, b: { lat: number; lon: number }): number {
  const rad = Math.PI / 180;
  const h = Math.sin((b.lat - a.lat) * rad / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin((b.lon - a.lon) * rad / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(h));
}

/** The saved case closest to a point; region cases (lat/lon 0,0 placeholders) never win on distance. */
export function nearestCase(point: { lat: number; lon: number }): DemoCase {
  const located = demoCases.filter(item => !item.result.case.place.place_id.startsWith('region:'));
  return (located.length ? located : demoCases).reduce((best, item) => km(point, item.result.case.place) < km(point, best.result.case.place) ? item : best);
}
