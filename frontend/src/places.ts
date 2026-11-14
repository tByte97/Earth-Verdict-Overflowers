import type { Place } from './types';

const aliases: Record<string, readonly string[]> = {
  'city:kyiv': ['Kyiv', 'Київ'],
  'city:lviv': ['Lviv', 'Львів'],
};

export function matchesPlace(place: Place, query: string): boolean {
  const terms = [place.name, place.place_id, ...(aliases[place.place_id] ?? [])];
  return terms.some(term => term.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
}
