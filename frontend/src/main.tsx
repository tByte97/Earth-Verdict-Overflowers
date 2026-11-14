import { StrictMode, Suspense, lazy, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { demoCases, findPlaces, getVariables, isLive, runCheck } from './api';
import { VerdictCard } from './VerdictCard';
import { ErrorBoundary } from './ErrorBoundary';
import { CaseSpecSchema } from './schema';
import type { CaseSpec, CheckResult, Place, Variable } from './types';
import type { PickedPoint } from './globe/Globe';
import './styles.css';

const Globe = lazy(() => import('./globe/Globe').then(module => ({ default: module.Globe })));

const seasons = [['year', 'Whole year'], ['DJF', 'Winter · Dec–Feb'], ['MAM', 'Spring · Mar–May'], ['JJA', 'Summer · Jun–Aug'], ['SON', 'Autumn · Sep–Nov'], ...Array.from({ length: 12 }, (_, i) => [String(i + 1), new Intl.DateTimeFormat('en', { month: 'long' }).format(new Date(2000, i, 1))])];

function App() {
  const initial = demoCases[0];
  const [demoId, setDemoId] = useState(initial.id);
  const [spec, setSpec] = useState<CaseSpec>(isLive ? { claim_text: '', variable_id: '', place: { place_id: '', name: '', lat: 0, lon: 0 }, season: 'year', start_year: 1981, end_year: 2025, claim_direction: 'change' } : initial.result.case);
  const [result, setResult] = useState<CheckResult | null>(isLive ? null : initial.result);
  const [variables, setVariables] = useState<Variable[]>(isLive ? [] : [initial.result.variable]);
  const [query, setQuery] = useState(isLive ? '' : initial.result.case.place.name);
  const [places, setPlaces] = useState<Place[]>([]);
  const [selectedPlace, setSelectedPlace] = useState(!isLive);
  const [searchStatus, setSearchStatus] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState<'initial' | 'edited' | 'loading' | 'success' | 'error'>(isLive ? 'initial' : 'success');
  const [catalogueLoading, setCatalogueLoading] = useState(true);
  const [help, setHelp] = useState(false);
  const [picked, setPicked] = useState<PickedPoint | null>(null);
  const request = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getVariables(controller.signal).then(values => {
      if (controller.signal.aborted) return;
      setVariables(values);
      setSpec(current => ({ ...current, variable_id: values.some(value => value.id === current.variable_id) ? current.variable_id : values[0].id }));
      setCatalogueLoading(false);
    }).catch(e => {
      if (controller.signal.aborted) return;
      setError(`Cannot load variables: ${e.message}`); setCatalogueLoading(false); setPhase('error');
    });
    return () => { controller.abort(); request.current?.abort(); };
  }, []);

  function edit(next: Partial<CaseSpec>) {
    request.current?.abort(); setBusy(false); setError(''); setResult(null); setPhase('edited'); setSpec(current => ({ ...current, ...next }));
  }
  useEffect(() => {
    if (selectedPlace || query.trim().length < 2) { setPlaces([]); setSearchStatus(''); return; }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setSearchStatus('Searching…');
      findPlaces(query, controller.signal).then(items => {
        if (!controller.signal.aborted) { setPlaces(items); setSearchStatus(items.length ? 'Select a place below.' : isLive ? 'No places found. Try another name.' : 'No places found. Saved cases cover Kyiv and Lviv.'); }
      }).catch(e => { if (e.name !== 'AbortError') setSearchStatus(`Search failed: ${e.message}`); });
    }, 250);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [query, selectedPlace]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!variables.some(variable => variable.id === spec.variable_id)) { setError('Select an available backend variable.'); setPhase('error'); return; }
    if (!selectedPlace) { setPhase('error'); setError('Select a place from the search results first.'); return; }
    if (!Number.isInteger(spec.start_year) || !Number.isInteger(spec.end_year) || spec.start_year > spec.end_year) { setPhase('error'); setError('Choose valid years: the start must not be after the end.'); return; }
    request.current?.abort(); const controller = new AbortController(); request.current = controller;
    setBusy(true); setPhase('loading'); setResult(null); setError('');
    try { const response = await runCheck(spec, demoId, controller.signal); if (!controller.signal.aborted) { setResult(response); setPhase('success'); } }
    catch (e) { if (!controller.signal.aborted) { setError(e instanceof Error ? e.message : 'The check failed. Please try again.'); setPhase('error'); } }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }

  function chooseDemo(id: string) {
    const next = demoCases.find(item => item.id === id)!;
    request.current?.abort(); setBusy(false); setDemoId(id); setSpec(next.result.case);
    setQuery(next.result.case.place.name); setSelectedPlace(true); setPicked(null); setError(''); setResult(next.result); setPhase('success');
  }

  return <>
    <header className="site-header"><a className="brand" href="./"><span className="brand-mark" aria-hidden="true">◉</span> Earth Verdict<span className="brand-caption">EVIDENCE, CLEARLY</span></a><button className="help-button" type="button" onClick={() => setHelp(v => !v)} aria-expanded={help}>How to use <span aria-hidden="true">?</span></button></header>
    <main>
      <div className="intro"><p className="eyebrow">A closer look at our changing planet</p><h1>A claim. A check.<br /><span>A clearer answer.</span></h1><p>Choose what you want to investigate.<br />See the conclusion, then explore the evidence behind it.</p></div>
      {help && <section className="tutorial" aria-label="Quick tutorial"><h2>Your first check</h2><ol><li><strong>Choose your case.</strong> Set a place, variable, season, years and direction.</li><li><strong>Run the check.</strong> Read the verdict, rate of change and station status.</li><li><strong>Explore the evidence.</strong> Open “How we checked this” for every number, or “Data sources” for provenance.</li></ol><p>“Not proven” means evidence is insufficient; it does not mean there is no change.</p><button type="button" className="text-button" onClick={() => setHelp(false)}>Got it · close guide</button></section>}
      <div className={`mode-banner ${isLive ? 'live' : ''}`}><div><span className="eyebrow">{isLive ? 'Connected mode' : 'Shared backend snapshots'}</span><p>{isLive ? 'Checks are sent to your backend. No synthetic fallback.' : 'Real observations · provisional statistics. Choose a case to explore the team’s JSON response.'}</p></div><a href={isLive ? './' : 'https://github.com/tByte97/Earth-Verdict-Overflowers/tree/main/data/cases'}>{isLive ? 'Open saved cases' : 'View shared JSON'} <span aria-hidden="true">↗</span></a></div>
      <div className="workspace">
        <section className="globe-column" aria-label="Case location">
          <div className="globe-heading"><span className="eyebrow">Explore the planet</span><p>{selectedPlace ? spec.place.name : 'Choose a place or pick a point'}</p></div>
          <ErrorBoundary><Suspense fallback={<div className="map-loading" role="status">Loading globe…</div>}><Globe place={selectedPlace ? spec.place : null} station={result?.witness?.station ?? null} onPick={point => {
            setPicked(point); setSelectedPlace(true); setQuery('Selected point');
            edit({ place: { place_id: `point:${point.lat},${point.lon}`, name: 'Selected point', lat: point.lat, lon: point.lon } });
          }} /></Suspense></ErrorBoundary>
          <div className="globe-legend"><span><i className="legend-place" />Case point</span><span><i className="legend-station" />Ground station</span></div>
        </section>
        <div className="investigation-panel">
        <aside className="case-panel" aria-labelledby="case-heading">
          <div className="panel-heading"><span className="step">01</span><div><p className="eyebrow">Your investigation</p><h2 id="case-heading">Set up a check</h2></div></div>
          {!isLive && <label className="demo-select">Saved case<select value={demoId} onChange={e => chooseDemo(e.target.value)}>{demoCases.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>}
          <details className="case-parameters" open={!result}><summary>Edit parameters</summary>
          <form onSubmit={submit}>
            <label>Claim<input required value={spec.claim_text} onChange={e => edit({ claim_text: e.target.value })} /></label>
            <p className="field-help">The structured parameters below define the actual check. Saved wording comes from the backend response.</p>
            <label>Place<input required value={query} autoComplete="off" onChange={e => { setQuery(e.target.value); setSelectedPlace(false); edit({}); }} aria-describedby="place-status" /></label>
            <p className="field-help" id="place-status" role="status">{selectedPlace ? 'Place selected. Type to search for another.' : searchStatus || 'Type at least two characters, then select a result.'}</p>
            {picked && <p className="field-help" role="status">Picked coordinates: {picked.lat.toFixed(4)}, {picked.lon.toFixed(4)}</p>}
            {places.length > 0 && <ul className="place-results" aria-label="Place search results">{places.map(place => <li key={place.place_id}><button type="button" onClick={() => { edit({ place }); setQuery(place.name); setSelectedPlace(true); setPlaces([]); setPicked(null); }}>{place.name}</button></li>)}</ul>}
            <label>Variable<select required value={spec.variable_id} disabled={catalogueLoading || !variables.length} onChange={e => edit({ variable_id: e.target.value })}>{!variables.length && <option value="">{catalogueLoading ? 'Loading variables…' : 'No variables available'}</option>}{variables.map(v => <option key={v.id} value={v.id}>{v.label} · {v.units}</option>)}</select></label>
            <label>Season<select value={spec.season} onChange={e => edit({ season: CaseSpecSchema.shape.season.parse(/^\d+$/.test(e.target.value) ? Number(e.target.value) : e.target.value) })}>{seasons.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <fieldset><legend>Observation period</legend><div className="year-fields"><label>From<input type="number" required min="1" max="9999" value={Number.isNaN(spec.start_year) ? '' : spec.start_year} onChange={e => edit({ start_year: e.target.valueAsNumber })} /></label><span aria-hidden="true">—</span><label>To<input type="number" required min="1" max="9999" value={Number.isNaN(spec.end_year) ? '' : spec.end_year} onChange={e => edit({ end_year: e.target.valueAsNumber })} /></label></div></fieldset>
            <label>Claim direction<select value={spec.claim_direction} onChange={e => edit({ claim_direction: e.target.value as CaseSpec['claim_direction'] })}><option value="increase">Increasing</option><option value="decrease">Decreasing</option><option value="change">Changing in either direction</option></select></label>
            {error && <div className="error" role="alert">{error}</div>}
            <button className="primary-button" type="submit" disabled={busy || catalogueLoading || !variables.length}>{busy ? 'Checking…' : 'Check claim'} <span aria-hidden="true">→</span></button>
            <p className="field-help">{isLive ? 'Your backend performs the calculations.' : 'Saved cases return the team’s JSON unchanged. Custom periods require the calculation API.'}</p>
          </form>
          </details>
        </aside>
        <section className="result-panel" aria-label="Check result" aria-busy={busy}>
          <div className="result-heading"><span className="step">02</span><p className="eyebrow">The evidence, in focus</p></div>
          <div id="result-status" role="status" aria-live="polite" aria-atomic="true" className="sr-only">{phase === 'loading' ? 'Check in progress.' : phase === 'error' ? `Check unavailable. ${error}` : phase === 'success' && result ? `Result: ${result.verdict.replace('_', ' ')}.` : phase === 'edited' ? 'Parameters changed. Run a check to see the result.' : catalogueLoading ? 'Loading available variables.' : 'Ready to configure a check.'}</div>
          {result ? <ErrorBoundary key={JSON.stringify(result.case) + result.verdict}><VerdictCard result={result} saved={!isLive} /></ErrorBoundary> : <div className="empty-state"><span aria-hidden="true">◎</span><h2>{busy ? 'Checking the evidence…' : 'Ready when you are.'}</h2><p>{busy ? 'Waiting for a response from the backend.' : 'Set your parameters and select “Check claim”. Your result will appear here.'}</p></div>}
        </section>
        </div>
      </div>
      <footer><span>Earth Verdict · Team Overflowers</span><p>Past observations describe evidence about change. They are not a forecast.</p></footer>
    </main>
  </>;
}

createRoot(document.getElementById('root')!).render(<StrictMode><ErrorBoundary><App /></ErrorBoundary></StrictMode>);
