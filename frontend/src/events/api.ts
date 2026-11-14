import { z } from 'zod';
import { isLive, request } from '../api';
import type { Place } from '../types';
import {
  ChatResponseSchema, Co2ImpactSchema, CompoundSchema, EventProfileSchema, EventResultSchema, EventSiteSchema,
  type ChatResponse, type Co2Impact, type Compound, type EventProfile, type EventResult, type EventSite, type EventSpec,
} from './schema';
import { savedEvents } from './data';

// Satellite series for a new place are downloaded point by point from NASA Giovanni; the first
// request for a place can take a couple of minutes, later ones are cached on the server.
const SLOW = 240_000;
const json = (body: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

function parse<T>(schema: z.ZodType<T>, data: unknown, what: string): T {
  const parsed = schema.safeParse(data);
  if (!parsed.success) throw new Error(`Invalid ${what} returned by the backend (${parsed.error.issues.map(i => i.path.join('.') || 'root').slice(0, 3).join(', ')}).`);
  return parsed.data;
}

export async function getCompounds(signal?: AbortSignal): Promise<Compound[]> {
  if (!isLive) return [...new Map(savedEvents.map(e => [e.result.compound.id, e.result.compound])).values()];
  return parse(z.array(CompoundSchema), await request('/compounds', undefined, signal), 'compound list');
}

export async function getEventSites(signal?: AbortSignal): Promise<EventSite[]> {
  if (!isLive) return savedEvents.map(e => e.site);
  return parse(z.array(EventSiteSchema), await request('/event-sites', undefined, signal), 'event list');
}

export async function getProfile(spec: { compound_id: string; place: Place; window_years: number; use_control: boolean }, signal?: AbortSignal): Promise<EventProfile> {
  return parse(EventProfileSchema, await request('/event/profile', json(spec), signal, SLOW), 'event profile');
}

export async function runEvent(spec: EventSpec, signal?: AbortSignal): Promise<EventResult> {
  if (!isLive) {
    const saved = savedEvents.find(e => e.result.spec.place.place_id === spec.place.place_id && e.result.spec.event_month === spec.event_month &&
      e.result.spec.window_years === spec.window_years && e.result.spec.compound_id === spec.compound_id && e.result.spec.use_control === spec.use_control);
    if (!saved) throw new Error('Saved mode only has the ready-made events. Connect the backend to move the date.');
    return structuredClone(saved.result);
  }
  return parse(EventResultSchema, await request('/event', json(spec), signal, SLOW), 'event result');
}

export async function savedEvent(id: string, signal?: AbortSignal): Promise<EventResult> {
  const local = savedEvents.find(e => e.site.id === id);
  if (!isLive && local) return structuredClone(local.result);
  return parse(EventResultSchema, await request(`/events/${encodeURIComponent(id)}`, undefined, signal), 'event result');
}

export async function runCo2(spec: { mt_co2_per_year: number; years: number; what_if_ppm?: number; label?: string }, signal?: AbortSignal): Promise<Co2Impact> {
  return parse(Co2ImpactSchema, await request('/co2-impact', json(spec), signal, 60_000), 'CO₂ result');
}

export async function explain(kind: 'check' | 'event' | 'co2', result: unknown, question: string | null, lang: 'en' | 'uk', signal?: AbortSignal): Promise<ChatResponse> {
  return parse(ChatResponseSchema, await request('/chat', json({ kind, result, question: question || null, lang }), signal, 60_000), 'explanation');
}
