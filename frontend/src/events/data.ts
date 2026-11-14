import sites from '../../../data/events/_sites.json';
import { EventResultSchema, EventSiteSchema, type EventResult, type EventSite } from './schema';

// The team's precomputed events (tools/build_events.py), used when no backend is connected.
const files = import.meta.glob('../../../data/events/*.json', { eager: true, import: 'default' }) as Record<string, unknown>;
const byId = new Map(Object.entries(files).map(([path, data]) => [path.split('/').pop()!.replace('.json', ''), data]));

export const savedEvents: { site: EventSite; result: EventResult }[] = sites.map(raw => {
  const site = EventSiteSchema.parse(raw);
  return { site, result: EventResultSchema.parse(byId.get(site.id)) };
});
