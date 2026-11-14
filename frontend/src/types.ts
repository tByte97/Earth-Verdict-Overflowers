export type Verdict = 'confirmed' | 'refuted' | 'not_proven';
export type Reason = 'significant_trend' | 'opposite_trend' | 'not_significant' | 'short_series' | 'sources_disagree' | 'not_robust';
export interface Place { place_id: string; name: string; lat: number; lon: number }
export interface Variable { id: string; label: string; units: string; definition: string; caveat?: string | null }
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
  mk: { p: number | null; tau?: number | null; z?: number | null; correction?: string };
  ols: { slope_per_year: number | null; p: number | null; r2?: number | null; n_eff?: number | null };
  robustness: { start_year: number; end_year: number; p: number | null; slope_per_decade: number | null; significant: boolean }[];
  robustness_summary: { significant: number; total: number };
  witness: null | {
    station: { id: string; name: string; lat: number; lon: number; distance_km: number };
    series: { year: number; value: number | null }[]; sen: Trend; mk: { p: number | null };
    coverage?: number; method_note?: string | null;
    agreement: 'agree' | 'one_source' | 'disagree';
  };
  verdict: Verdict; reason: Reason; years_to_wait: number | null; provenance: Provenance[];
  steps?: { id: string; title: string; value: string; detail: string }[];
  detection?: { residual_sd: number; phi: number; slope_per_year: number; n_years: number; multipliers: number[]; years_needed: (number | null)[] };
  extrapolation?: { note: string; from_year: number; from_value: number; years: number[]; paths: { id: string; label: string; multiplier: number; central: number[]; low: number[]; high: number[] }[] };
  scenarios?: null | { synthetic: boolean; source: string; baseline_period: string; baseline_value: number; note: string; paths: { id: string; label: string; years: number[]; median: number[]; low: number[]; high: number[] }[] };
  meta?: { stub: boolean; stats_engine: string; generated_at: string };
}
export interface DemoCase { id: string; label: string; result: CheckResult }
