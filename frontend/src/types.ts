import type { z } from 'zod';
import type { CaseSpecSchema, CheckResultSchema, PlaceSchema, ProvenanceSchema, VariableSchema } from './schema';

export type CaseSpec = z.infer<typeof CaseSpecSchema>;
export type CheckResult = z.infer<typeof CheckResultSchema>;
export type Place = z.infer<typeof PlaceSchema>;
export type Variable = z.infer<typeof VariableSchema>;
export type Provenance = z.infer<typeof ProvenanceSchema>;
export type Verdict = CheckResult['verdict'];
export type Reason = CheckResult['reason'];
export interface DemoCase { id: string; label: string; result: CheckResult }
