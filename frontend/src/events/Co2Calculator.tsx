import { useEffect, useRef, useState } from 'react';
import { isLive } from '../api';
import { number } from '../format';
import { runCo2 } from './api';
import { Explain } from './Explain';
import type { Co2Impact } from './schema';
import './events.css';

// Emissions slider is logarithmic: 0.1 to 1,000 Mt CO2 per year (a large coal plant is ~10-20).
const toMt = (s: number) => +(10 ** (s / 25 - 1)).toPrecision(2);
const fromMt = (mt: number) => Math.round((Math.log10(mt) + 1) * 25);
const presets = [
  { label: 'Large coal plant', mt: 15, years: 40 },
  { label: 'City of 1 million', mt: 6, years: 30 },
  { label: 'A country like Ukraine, 10 years', mt: 180, years: 10 },
];

export function Co2Calculator() {
  const [mt, setMt] = useState(15);
  const [years, setYears] = useState(40);
  const [whatIf, setWhatIf] = useState(560);
  const [useWhatIf, setUseWhatIf] = useState(true);
  const [result, setResult] = useState<Co2Impact | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const req = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!isLive) return;
    const t = window.setTimeout(() => {
      req.current?.abort(); const c = new AbortController(); req.current = c;
      setBusy(true); setError('');
      runCo2({ mt_co2_per_year: mt, years, ...(useWhatIf ? { what_if_ppm: whatIf } : {}) }, c.signal)
        .then(r => { if (!c.signal.aborted) setResult(r); })
        .catch(e => { if (!c.signal.aborted) setError(e.message); })
        .finally(() => { if (!c.signal.aborted) setBusy(false); });
    }, 300);
    return () => window.clearTimeout(t);
  }, [mt, years, whatIf, useWhatIf]);
  useEffect(() => () => req.current?.abort(), []);

  if (!isLive) return <div className="empty-state"><span aria-hidden="true">◎</span><h2>The CO₂ calculator needs the backend.</h2><p>Open the connected version to use it.</p></div>;

  const r = result;
  return <div className="ev-workspace">
    <aside className="case-panel ev-controls" aria-labelledby="co2-heading">
      <div className="panel-heading"><span className="step">01</span><div><p className="eyebrow">Carbon dioxide</p><h2 id="co2-heading">What does one source add?</h2></div></div>
      <p className="field-help">CO₂ mixes around the whole planet within weeks, so one plant cannot be seen against its neighbours. Instead we turn its emissions into what they add to the global air, with published physics.</p>
      <div className="ev-presets">{presets.map(p => <button key={p.label} type="button" className="chip" onClick={() => { setMt(p.mt); setYears(p.years); }}>{p.label}</button>)}</div>
      <label><span>Emissions: <strong>{number(mt)} Mt CO₂ per year</strong></span><input type="range" min={0} max={100} value={fromMt(mt)} onChange={e => setMt(toMt(Number(e.target.value)))} /></label>
      <label><span>For <strong>{years} years</strong></span><input type="range" min={1} max={100} value={years} onChange={e => setYears(Number(e.target.value))} /></label>
      <label className="ev-toggle"><input type="checkbox" checked={useWhatIf} onChange={e => setUseWhatIf(e.target.checked)} /> Also show: what if the whole atmosphere had…</label>
      {useWhatIf && <label><span><strong>{whatIf} ppm</strong> of CO₂ (pre-industrial: 280)</span><input type="range" min={280} max={1200} step={10} value={whatIf} onChange={e => setWhatIf(Number(e.target.value))} /></label>}
      {error && <div className="error" role="alert">{error}</div>}
    </aside>
    <section className="result-panel ev-main" aria-busy={busy}>
      {r ? <article className={`verdict-card ev-card ${busy ? 'ev-stale' : ''}`}>
        <div className="card-top"><span className="eyebrow">Physics estimate · not an observation</span><span className="tag">Backend response</span></div>
        <h2 className="claim">{number(r.spec.mt_co2_per_year)} Mt CO₂ a year for {number(r.spec.years)} years</h2>
        <div className="co2-grid">
          <div className="headline-metric"><span className="eyebrow">Emitted in total</span><div className="metric-value">{number(r.total_emitted_gt)} <span>Gt CO₂</span></div></div>
          <div className="headline-metric"><span className="eyebrow">Added to the global air</span><div className="metric-value">{number(r.added_ppm.central, true)} <span>ppm</span></div><p>range {number(r.added_ppm.low)} to {number(r.added_ppm.high)} ppm, on top of {number(r.global_co2.latest_ppm)} ppm today ({r.global_co2.latest_month})</p></div>
          <div className="headline-metric"><span className="eyebrow">Warming it causes</span><div className="metric-value">{number(r.transient_warming_c.central, true)} <span>°C</span></div><p>likely range {number(r.transient_warming_c.low)} to {number(r.transient_warming_c.high)} °C</p></div>
        </div>
        <p className="caution"><strong>Small for one source, large for all of them.</strong> Global CO₂ is rising by {number(r.global_co2.yoy_growth_ppm, true)} ppm a year ({number(r.global_co2.sen_slope_ppm_per_year, true)} ppm a year on average since 1980): the sum of everyone’s emissions.</p>
        {r.what_if_warming_c && <div className="headline-metric"><span className="eyebrow">What if the atmosphere had {number(r.spec.what_if_ppm)} ppm</span><div className="metric-value">{number(r.what_if_warming_c.central, true)} <span>°C vs pre-industrial</span></div><p>likely range {number(r.what_if_warming_c.low)} to {number(r.what_if_warming_c.high)} °C · extra heating {number(r.what_if_forcing_w_m2)} W/m² · transient response, before slow feedbacks</p></div>}
        <details className="technical"><summary>How we calculated this <span>Constants & sources</span></summary><div className="detail-body">
          <p className="help-text">{r.explanation}</p>
          <p className="help-text">About 44% (40–48%) of emitted CO₂ stays in the air; 1 ppm ≈ 7.82 Gt CO₂ (Global Carbon Budget). Extra heating ΔF = 5.35 · ln(C/C₀) W/m² (Myhre et al., 1998). Warming = TCR · ln(C/C₀) / ln 2, TCR 1.8 °C (1.4–2.2, IPCC AR6).</p>
          {r.provenance.map((s, i) => <p className="help-text" key={i}><strong>{s.source}</strong> · {s.product} · retrieved {s.retrieved_at}</p>)}
        </div></details>
        <Explain kind="co2" result={r} />
      </article> : <div className="empty-state"><span aria-hidden="true">◎</span><h2>{busy ? 'Calculating…' : 'Move a slider.'}</h2></div>}
    </section>
  </div>;
}
