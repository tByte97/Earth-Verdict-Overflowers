import { z } from 'zod';
import { PlaceSchema, ProvenanceSchema } from '../schema';

const finite = z.number().finite();
const integer = finite.int();
const month = z.string().regex(/^\d{4}-\d{2}$/);
const MonthValueSchema = z.object({ month, value: finite.nullable() });
const reason = z.enum(['clear_change', 'not_significant', 'placebo_also_changes', 'too_short', 'no_placebo']);
const verdict = z.enum(['clear_change', 'not_proven']);
const MetaSchema = z.object({ stub: z.boolean(), stats_engine: z.string(), generated_at: z.string() });

export const CompoundSchema = z.object({
  id: z.string(), label: z.string(), units: z.string(), definition: z.string(), caveat: z.string().nullable().optional(),
  product: z.string(), first_year: integer, last_year: integer, local_signal: z.boolean(), kind: z.enum(['satellite', 'reanalysis']),
  event_bounds: z.array(z.object({ window_years: integer, earliest: month, latest: month })),
  valid_windows: z.array(integer).optional(),
});

export const EventSiteSchema = z.object({
  id: z.string(), label: z.string(), kind: z.enum(['opening', 'closure', 'lockdown', 'eruption', 'check']), place: PlaceSchema,
  compound_id: z.string(), event_month: month, window_years: integer, note: z.string(), saved: z.boolean(),
});

export const EventSpecSchema = z.object({
  compound_id: z.string(), place: PlaceSchema, event_month: month, event_label: z.string(), window_years: integer, use_control: z.boolean(),
});

export const EventResultSchema = z.object({
  spec: EventSpecSchema, compound: CompoundSchema, site: z.array(MonthValueSchema), control: z.array(MonthValueSchema).nullable(),
  before: z.object({ start: month, end: month, mean: finite.nullable(), n: integer }),
  after: z.object({ start: month, end: month, mean: finite.nullable(), n: integer }),
  effect: finite.nullable(), ci_low: finite.nullable(), ci_high: finite.nullable(),
  bootstrap_ci_low: finite.nullable(), bootstrap_ci_high: finite.nullable(), p: finite.nullable(), relative_change: finite.nullable(),
  placebo: z.array(z.object({ event_month: month, effect: finite, p: finite })), placebo_larger: integer,
  verdict, direction: z.enum(['increase', 'decrease', 'none']), reason,
  sen_before: z.object({ slope_per_year: finite, ci_low: finite, ci_high: finite }).nullable(),
  sen_after: z.object({ slope_per_year: finite, ci_low: finite, ci_high: finite }).nullable(),
  steps: z.array(z.object({ id: z.string(), title: z.string(), value: z.string(), detail: z.string() })),
  provenance: z.array(ProvenanceSchema), meta: MetaSchema,
});

export const ProfilePointSchema = z.object({
  event_month: month, effect: finite.nullable(), ci_low: finite.nullable(), ci_high: finite.nullable(), p: finite.nullable(),
  verdict, reason, n_placebo: integer, placebo_larger: integer,
});

export const EventProfileSchema = z.object({
  spec: z.object({ compound_id: z.string(), place: PlaceSchema, window_years: integer, use_control: z.boolean() }),
  compound: CompoundSchema, site: z.array(MonthValueSchema), control: z.array(MonthValueSchema).nullable(),
  earliest: month, latest: month, points: z.array(ProfilePointSchema), provenance: z.array(ProvenanceSchema), meta: MetaSchema,
});

const RangeSchema = z.object({ central: finite, low: finite, high: finite });
export const Co2ImpactSchema = z.object({
  spec: z.object({ mt_co2_per_year: finite, years: finite, what_if_ppm: finite.nullable().optional(), c0_ppm: finite, label: z.string().nullable().optional() }),
  total_emitted_gt: finite, added_ppm: RangeSchema, added_forcing_w_m2: RangeSchema, transient_warming_c: RangeSchema,
  what_if_forcing_w_m2: finite.nullable().optional(), what_if_warming_c: RangeSchema.nullable().optional(),
  global_co2: z.object({ latest_month: month, latest_ppm: finite, yoy_growth_ppm: finite.nullable(), sen_slope_ppm_per_year: finite, sen_ci_low: finite, sen_ci_high: finite, series: z.array(MonthValueSchema) }),
  explanation: z.string(), provenance: z.array(ProvenanceSchema),
});

export const ChatResponseSchema = z.object({ text: z.string(), model: z.string(), grounded: z.boolean() });

export type Compound = z.infer<typeof CompoundSchema>;
export type EventSite = z.infer<typeof EventSiteSchema>;
export type EventSpec = z.infer<typeof EventSpecSchema>;
export type EventResult = z.infer<typeof EventResultSchema>;
export type EventProfile = z.infer<typeof EventProfileSchema>;
export type ProfilePoint = z.infer<typeof ProfilePointSchema>;
export type Co2Impact = z.infer<typeof Co2ImpactSchema>;
export type ChatResponse = z.infer<typeof ChatResponseSchema>;
