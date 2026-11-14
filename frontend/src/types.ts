export type Verdict = 'confirmed' | 'refuted' | 'not_proven';
export type Reason = 'significant_trend' | 'opposite_trend' | 'not_significant' | 'short_series' | 'sources_disagree' | 'not_robust';
export interface Place { place_id: string; name: string; lat: number; lon: number }
export interface Variable { id: string; label: string; units: string; definition: string; caveat: string }
export interface CaseSpec {
  claim_text: string; variable_id: string; place: Place;
  season: string | number; start_year: number; end_year: number;
  claim_direction: 'increase' | 'decrease' | 'change';
}
export interface Trend {
  slope_per_year?: number | null; slope_per_decade: number | null;
  ci_low?: number | null; ci_high?: number | null; intercept?: number | null;
}
export interface Provenance {
  what: string; source: string; product: string; url: string;
  retrieved_at: string; license: string; version?: string;
}
export interface CheckResult {
  case: CaseSpec; variable: Variable;
  series: { year: number; value: number | null }[];
  sen: Trend;
  mk: { p: number | null; tau?: number | null; z?: number | null; correction?: string; r1?: number | null };
  ols: { slope_per_year: number | null; p: number | null; r2?: number | null; n_eff?: number | null };
  robustness: { start_year: number; end_year: number; p: number | null; slope_per_decade: number | null; significant: boolean }[];
  robustness_summary: { significant: number; total: number };
  witness: null | {
    station: { id: string; name: string; lat: number; lon: number; distance_km: number };
    series: { year: number; value: number | null }[]; sen: Trend; mk: { p: number | null };
    agreement: 'agree' | 'one_source' | 'disagree' | 'no_station';
  };
  verdict: Verdict; reason: Reason; years_to_wait: number | null; provenance: Provenance[];
  // Optional additive metadata, pending backend agreement; never inferred for ambiguous fields.
  presentation?: { baseline?: string | null; ci_units?: { sen?: string; witness?: string } };
}
export interface DemoCase { id: string; label: string; result: CheckResult }
