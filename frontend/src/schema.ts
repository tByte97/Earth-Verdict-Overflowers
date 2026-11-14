import { z } from 'zod';

// Runtime schemas follow backend/app/models.py; TypeScript types are inferred from them.
const finite = z.number().finite();
const integer = finite.int();
export const PlaceSchema = z.object({ place_id: z.string(), name: z.string(), lat: finite.min(-90).max(90), lon: finite.min(-180).max(180) }).strict();
export const VariableSchema = z.object({ id: z.string().min(1), label: z.string(), units: z.string(), definition: z.string(), caveat: z.string().nullable().optional() }).strict();
export const CaseSpecSchema = z.object({
  claim_text: z.string(), variable_id: z.string(), place: PlaceSchema,
  season: z.union([z.enum(['year', 'DJF', 'MAM', 'JJA', 'SON']), integer.min(1).max(12)]),
  start_year: integer, end_year: integer, claim_direction: z.enum(['increase', 'decrease', 'change']),
}).strict();
const YearValueSchema = z.object({ year: integer, value: finite.nullable() }).strict();
const WitnessSenSchema = z.object({ slope_per_decade: finite, ci_low: finite, ci_high: finite }).strict();
const SenSchema = WitnessSenSchema.extend({ slope_per_year: finite, intercept: finite }).strict();
const MKSchema = z.object({ p: finite, tau: finite, z: finite, correction: z.enum(['hamed_rao', 'none']) }).strict();
const OLSSchema = z.object({ slope_per_year: finite, p: finite, r2: finite, n_eff: finite }).strict();
const WitnessRatesSchema = z.object({
  common_years: integer, main_slope_per_decade: finite, witness_slope_per_decade: finite,
  difference_per_decade: finite, ci_low: finite, ci_high: finite, p: finite, consistent: z.boolean(),
}).strict();
const WitnessSchema = z.object({
  station: z.object({ id: z.string(), name: z.string(), lat: finite, lon: finite, distance_km: finite }).strict(),
  series: z.array(YearValueSchema), coverage: finite, method_note: z.string().nullable().optional(),
  sen: WitnessSenSchema, mk: z.object({ p: finite }).strict(),
  agreement: z.enum(['agree', 'one_source', 'disagree']),
  // Optional additive contract from feat/witness-rate-check; never invented by the UI.
  rates: WitnessRatesSchema.nullable().optional(),
}).strict();
const DetectionSchema = z.object({
  residual_sd: finite, phi: finite, slope_per_year: finite, n_years: integer,
  multipliers: z.array(finite), years_needed: z.array(finite.nullable()),
}).strict().refine(value => value.multipliers.length === value.years_needed.length, { message: 'Simulation array lengths differ' });
export const DetectionHistorySchema = z.object({
  alpha: finite.gt(0).lt(1), min_observations: integer.min(3),
  method: z.literal('sen_mann_kendall'), start_year: integer,
  points: z.array(z.object({
    end_year: integer, n_observations: integer.min(0), p: finite.min(0).max(1).nullable(),
    correction: z.enum(['hamed_rao', 'none']).nullable(), status: z.enum(['ok', 'short_series']),
  }).strict()).min(1),
}).strict().superRefine((history, ctx) => {
  let count = 0;
  history.points.forEach((point, i) => {
    const enough = point.n_observations >= history.min_observations;
    if (point.end_year !== history.start_year + i || ![0, 1].includes(point.n_observations - count) ||
      enough !== (point.status === 'ok') || enough !== (point.p !== null) || enough !== (point.correction !== null)) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['points', i], message: 'Inconsistent prefix check' });
    }
    count = point.n_observations;
  });
});
const ExtrapolationSchema = z.object({
  note: z.string(), from_year: integer, from_value: finite, years: z.array(integer),
  paths: z.array(z.object({ id: z.enum(['stop', 'slower', 'same', 'faster']), label: z.string(), multiplier: finite, central: z.array(finite), low: z.array(finite), high: z.array(finite) }).strict()),
}).strict().refine(value => value.paths.every(path => [path.central, path.low, path.high].every(values => values.length === value.years.length)), { message: 'Extrapolation array lengths differ' });
const ScenariosSchema = z.object({
  synthetic: z.boolean(), source: z.string(), baseline_period: z.string(), baseline_value: finite, note: z.string(),
  paths: z.array(z.object({ id: z.enum(['ssp126', 'ssp245', 'ssp585']), label: z.string(), years: z.array(integer), median: z.array(finite), low: z.array(finite), high: z.array(finite) }).strict()),
}).strict().refine(value => value.paths.every(path => [path.median, path.low, path.high].every(values => values.length === path.years.length)), { message: 'Scenario array lengths differ' });
export const ProvenanceSchema = z.object({ what: z.string(), source: z.string(), product: z.string(), url: z.string(), retrieved_at: z.string(), license: z.string(), version: z.string().nullable().optional() }).strict();
export const CheckResultSchema = z.object({
  case: CaseSpecSchema, variable: VariableSchema, series: z.array(YearValueSchema), sen: SenSchema, mk: MKSchema, ols: OLSSchema,
  robustness: z.array(z.object({ start_year: integer, end_year: integer, p: finite, slope_per_decade: finite, significant: z.boolean() }).strict()),
  robustness_summary: z.object({ significant: integer, total: integer }).strict(),
  witness: WitnessSchema.nullable(), verdict: z.enum(['confirmed', 'refuted', 'not_proven']),
  reason: z.enum(['significant_trend', 'opposite_trend', 'not_significant', 'short_series', 'sources_disagree', 'not_robust']),
  years_to_wait: integer.nullable(),
  steps: z.array(z.object({ id: z.enum(['raw', 'season', 'yearly', 'trend', 'random_check', 'robustness', 'witness', 'verdict']), title: z.string(), value: z.string(), detail: z.string() }).strict()),
  detection: DetectionSchema, detection_history: DetectionHistorySchema.nullable().optional(),
  extrapolation: ExtrapolationSchema, scenarios: ScenariosSchema.nullable(),
  provenance: z.array(ProvenanceSchema), meta: z.object({ stub: z.boolean(), stats_engine: z.string(), generated_at: z.string() }).strict(),
}).strict().superRefine((result, ctx) => {
  const history = result.detection_history;
  if (!history) return;
  let count = 0;
  const observations = new Map(result.series.map(point => [point.year, point.value]));
  if (history.start_year !== result.case.start_year || history.points.at(-1)?.end_year !== result.case.end_year) {
    ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['detection_history'], message: 'Prefix period differs from case' });
  }
  history.points.forEach((point, i) => {
    if (observations.get(point.end_year) != null) count++;
    if (point.n_observations !== count) ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['detection_history', 'points', i], message: 'Prefix count differs from observations' });
  });
});
export const ErrorResponseSchema = z.object({ error: z.object({ code: z.string(), message: z.string() }) });

export function parseCheckResult(input: unknown): z.infer<typeof CheckResultSchema> {
  const result = CheckResultSchema.safeParse(input);
  if (!result.success) {
    const fields = result.error.issues.map(issue => issue.path.join('.') || 'root').join(', ');
    throw new Error(`Invalid CheckResult response: ${fields}. Please check the backend contract.`);
  }
  return result.data;
}
