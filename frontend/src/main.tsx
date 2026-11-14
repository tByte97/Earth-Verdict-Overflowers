import { StrictMode, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { demoCases, findPlaces, getVariables, isLive, runCheck } from './api';
import { VerdictCard } from './VerdictCard';
import type { CaseSpec, CheckResult, Place, Variable } from './types';
import './styles.css';

const seasons = [['year', 'Whole year'], ['DJF', 'Winter · Dec–Feb'], ['MAM', 'Spring · Mar–May'], ['JJA', 'Summer · Jun–Aug'], ['SON', 'Autumn · Sep–Nov'], ...Array.from({ length: 12 }, (_, i) => [String(i + 1), new Intl.DateTimeFormat('en', { month: 'long' }).format(new Date(2000, i, 1))])];

function App() {
  const initial = demoCases[0];
  const [demoId, setDemoId] = useState(initial.id);
  const [spec, setSpec] = useState<CaseSpec>(initial.result.case);
  const [result, setResult] = useState<CheckResult | null>(isLive ? null : initial.result);
  const [variables, setVariables] = useState<Variable[]>(isLive ? [] : [initial.result.variable]);
  const [query, setQuery] = useState(initial.result.case.place.name);
  const [places, setPlaces] = useState<Place[]>([]);
  const [selectedPlace, setSelectedPlace] = useState(true);
  const [searchStatus, setSearchStatus] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [help, setHelp] = useState(false);
  const request = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getVariables(controller.signal).then(setVariables).catch(e => { if (e.name !== 'AbortError') setError(`Cannot load variables: ${e.message}`); });
    return () => { controller.abort(); request.current?.abort(); };
  }, []);

  function edit(next: Partial<CaseSpec>) {
    request.current?.abort(); setBusy(false); setError(''); setResult(null); setSpec(current => ({ ...current, ...next }));
  }
  useEffect(() => {
    if (selectedPlace || query.trim().length < 2) { setPlaces([]); setSearchStatus(''); return; }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setSearchStatus('Searching…');
      findPlaces(query, controller.signal).then(items => {
        if (!controller.signal.aborted) { setPlaces(items); setSearchStatus(items.length ? 'Select a place below.' : isLive ? 'No places found. Try another name.' : 'No places found. Demo search supports Kyiv only.'); }
      }).catch(e => { if (e.name !== 'AbortError') setSearchStatus(`Search failed: ${e.message}`); });
    }, 250);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [query, selectedPlace]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!selectedPlace) { setError('Select a place from the search results first.'); return; }
    if (!Number.isInteger(spec.start_year) || !Number.isInteger(spec.end_year) || spec.start_year > spec.end_year) { setError('Choose valid years: the start must not be after the end.'); return; }
    request.current?.abort(); const controller = new AbortController(); request.current = controller;
    setBusy(true); setResult(null); setError('');
    try { const response = await runCheck(spec, demoId, controller.signal); if (!controller.signal.aborted) setResult(response); }
    catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'The check failed. Please try again.'); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }

  function chooseDemo(id: string) {
    const next = demoCases.find(item => item.id === id)!;
    request.current?.abort(); setBusy(false); setDemoId(id); setSpec(next.result.case);
    setQuery(next.result.case.place.name); setSelectedPlace(true); setError(''); setResult(next.result);
  }

  return <>
    <header className="site-header"><a className="brand" href="./"><span className="brand-mark" aria-hidden="true">◉</span> Earth Verdict<span className="brand-caption">EVIDENCE, CLEARLY</span></a><button className="help-button" type="button" onClick={() => setHelp(v => !v)} aria-expanded={help}>How to use <span aria-hidden="true">?</span></button></header>
    <main>
      <div className="intro"><p className="eyebrow">A closer look at our changing planet</p><h1>A claim. A check.<br /><span>A clearer answer.</span></h1><p>Choose what you want to investigate.<br />See the conclusion, then explore the evidence behind it.</p></div>
      {help && <section className="tutorial" aria-label="Quick tutorial"><h2>Your first check</h2><ol><li><strong>Choose your case.</strong> Set a place, variable, season, years and direction.</li><li><strong>Run the check.</strong> Read the verdict, rate of change and station status.</li><li><strong>Explore the evidence.</strong> Open “How we checked this” for every number, or “Data sources” for provenance.</li></ol><p>“Not proven” means evidence is insufficient; it does not mean there is no change.</p><button type="button" className="text-button" onClick={() => setHelp(false)}>Got it · close guide</button></section>}
      <div className={`mode-banner ${isLive ? 'live' : ''}`}><div><span className="eyebrow">{isLive ? 'Connected mode' : 'Demo · synthetic data'}</span><p>{isLive ? 'Checks are sent to your backend. No synthetic fallback.' : 'Explore saved sample responses. These are not real climate findings.'}</p></div><a href={isLive ? '?source=demo' : '?source=live'}>{isLive ? 'Open demo' : 'Connect backend'} <span aria-hidden="true">↗</span></a></div>
      <div className="workspace">
        <aside className="case-panel" aria-labelledby="case-heading">
          <div className="panel-heading"><span className="step">01</span><div><p className="eyebrow">Your investigation</p><h2 id="case-heading">Set up a check</h2></div></div>
          {!isLive && <label className="demo-select">Saved demo response<select value={demoId} onChange={e => chooseDemo(e.target.value)}>{demoCases.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>}
          <form onSubmit={submit}>
            <label>Claim<input required value={spec.claim_text} onChange={e => edit({ claim_text: e.target.value })} /></label>
            <p className="field-help">The structured parameters below define the actual check. Demo wording comes from the saved response.</p>
            <label>Place<input required value={query} autoComplete="off" onChange={e => { setQuery(e.target.value); setSelectedPlace(false); edit({}); }} aria-describedby="place-status" /></label>
            <p className="field-help" id="place-status" role="status">{selectedPlace ? 'Place selected. Type to search for another.' : searchStatus || 'Type at least two characters, then select a result.'}</p>
            {places.length > 0 && <ul className="place-results" aria-label="Place search results">{places.map(place => <li key={place.place_id}><button type="button" onClick={() => { edit({ place }); setQuery(place.name); setSelectedPlace(true); setPlaces([]); }}>{place.name}</button></li>)}</ul>}
            <label>Variable<select required value={spec.variable_id} onChange={e => edit({ variable_id: e.target.value })}>{!variables.length && <option value="">Loading variables…</option>}{variables.map(v => <option key={v.id} value={v.id}>{v.label} · {v.units}</option>)}</select></label>
            <label>Season<select value={spec.season} onChange={e => edit({ season: /^\d+$/.test(e.target.value) ? Number(e.target.value) : e.target.value })}>{seasons.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <fieldset><legend>Observation period</legend><div className="year-fields"><label>From<input type="number" required min="1" max="9999" value={Number.isNaN(spec.start_year) ? '' : spec.start_year} onChange={e => edit({ start_year: e.target.valueAsNumber })} /></label><span aria-hidden="true">—</span><label>To<input type="number" required min="1" max="9999" value={Number.isNaN(spec.end_year) ? '' : spec.end_year} onChange={e => edit({ end_year: e.target.valueAsNumber })} /></label></div></fieldset>
            <label>Claim direction<select value={spec.claim_direction} onChange={e => edit({ claim_direction: e.target.value as CaseSpec['claim_direction'] })}><option value="increase">Increasing</option><option value="decrease">Decreasing</option><option value="change">Changing in either direction</option></select></label>
            {error && <div className="error" role="alert">{error}</div>}
            <button className="primary-button" type="submit" disabled={busy || !variables.length}>{busy ? 'Checking…' : 'Check claim'} <span aria-hidden="true">→</span></button>
            <p className="field-help">{isLive ? 'Your backend performs the calculations.' : 'Custom parameters need a connected backend. Demo checks return the selected saved JSON unchanged.'}</p>
          </form>
        </aside>
        <section className="result-panel" aria-label="Check result" aria-busy={busy}>
          <div className="result-heading"><span className="step">02</span><p className="eyebrow">The evidence, in focus</p></div>
          <div aria-live="polite" aria-atomic="true" className="sr-only">{busy ? 'Check in progress.' : result ? `Result: ${result.verdict.replace('_', ' ')}.` : 'Parameters changed. Run a check to see the result.'}</div>
          {result ? <VerdictCard key={JSON.stringify(result.case) + result.verdict} result={result} demo={!isLive} /> : <div className="empty-state"><span aria-hidden="true">◎</span><h2>{busy ? 'Checking the evidence…' : 'Ready when you are.'}</h2><p>{busy ? 'Waiting for a response from the backend.' : 'Set your parameters and select “Check claim”. Your result will appear here.'}</p></div>}
        </section>
      </div>
      <footer><span>Earth Verdict · Team Overflowers</span><p>Past observations describe evidence about change. They are not a forecast.</p></footer>
    </main>
  </>;
}

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>);
