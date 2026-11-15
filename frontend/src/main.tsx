import { StrictMode, Suspense, lazy, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { demoCases, findPlaces, getCase, getCases, getVariables, isLive, runCheck, type CaseItem } from './api';
import { VerdictCard } from './VerdictCard';
import { ErrorBoundary } from './ErrorBoundary';
import { CaseSpecSchema } from './schema';
import type { CaseSpec, CheckResult, Place, Variable } from './types';
import { pointPlace, type PickedPoint } from './globe/place';
import { seasonName, seasons, sourceIndex } from './format';
import { caseView, placeView, type Destination } from './globe/camera';
import { parseHash, writeHash } from './url';
import './styles.css';
import { Explain } from './events/Explain';

const EventsWorkspace = lazy(() => import('./events/EventsWorkspace').then(m => ({ default: m.EventsWorkspace })));
const Co2Calculator = lazy(() => import('./events/Co2Calculator').then(m => ({ default: m.Co2Calculator })));
type Mode = 'claims' | 'events' | 'co2';
const modes: [Mode, string][] = [['claims', 'Climate claims'], ['events', 'Pollution events'], ['co2', 'CO₂ calculator']];
const initialMode = (): Mode => { const m = new URLSearchParams(window.location.search).get('mode'); return m === 'events' || m === 'co2' ? m : 'claims'; };

const Globe = lazy(() => import('./globe/Globe').then(module => ({ default: module.Globe })));


const hashCase = () => { const state = parseHash(window.location.hash); return state?.kind === 'case' ? state.id : null; };
const savedResults = (): Record<string, CheckResult | 'error'> => isLive ? {} : Object.fromEntries(demoCases.map(item => [item.id, item.result]));

function App() {
  const initial = demoCases.find(item => item.id === hashCase()) ?? demoCases[0];
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
  const [mode, setModeState] = useState<Mode>(initialMode);
  function setMode(m: Mode) {
    setModeState(m);
    const url = new URL(window.location.href); if (m === 'claims') url.searchParams.delete('mode'); else url.searchParams.set('mode', m);
    window.history.replaceState(null, '', url);
  }
  const request = useRef<AbortController | null>(null);
  const [cases, setCases] = useState<CaseItem[]>(isLive ? [] : demoCases.map(item => ({ id: item.id, claim_text: item.result.case.claim_text })));
  // Full responses per case id; 'error' keeps the button working without its subtitle.
  const [caseResults, setCaseResults] = useState(savedResults);
  const [casesError, setCasesError] = useState('');
  const [caseId, setCaseId] = useState<string | null>(isLive ? null : initial.id);
  const flightKey = useRef(1);
  const [destination, setDestination] = useState<Destination | null>(isLive ? null : { key: 1, title: initial.result.case.claim_text, view: caseView(initial.result) });
  // In live mode the first case (or the linked one) opens as soon as it arrives, unless the user acted first.
  const autoOpen = useRef<string | null>(null);

  function flyTo(title: string, view: Destination['view']) { setDestination({ key: ++flightKey.current, title, view }); }
  function openCase(id: string, next: CheckResult) {
    autoOpen.current = null; request.current?.abort(); setBusy(false);
    setDemoId(id); setCaseId(id); setSpec(next.case); setQuery(next.case.place.name); setSelectedPlace(true); setPicked(null);
    setError(''); setResult(next); setPhase('success');
    flyTo(next.case.claim_text, caseView(next));
    writeHash({ kind: 'case', id });
  }
  async function chooseCase(id: string) {
    const known = caseResults[id];
    if (known && known !== 'error') { openCase(id, known); return; }
    autoOpen.current = null;
    try { const next = await getCase(id); setCaseResults(current => ({ ...current, [id]: next })); openCase(id, next); }
    catch (e) { setError(`Cannot open this case: ${e instanceof Error ? e.message : 'request failed'}`); setPhase('error'); }
  }
  const chooseCaseRef = useRef(chooseCase);
  chooseCaseRef.current = chooseCase;
  const caseIdRef = useRef(caseId);
  caseIdRef.current = caseId;

  useEffect(() => {
    if (!isLive) return;
    const controller = new AbortController();
    getCases(controller.signal).then(items => {
      if (controller.signal.aborted) return;
      setCases(items);
      autoOpen.current = items.find(item => item.id === hashCase())?.id ?? items[0]?.id ?? null;
      // All cases load in parallel; each button gets its subtitle when its response arrives.
      for (const item of items) getCase(item.id, controller.signal).then(next => {
        setCaseResults(current => ({ ...current, [item.id]: next }));
        if (autoOpen.current === item.id) openCase(item.id, next);
      }).catch(() => { if (!controller.signal.aborted) setCaseResults(current => ({ ...current, [item.id]: 'error' })); });
    }).catch(e => { if (!controller.signal.aborted) setCasesError(`Saved cases are unavailable: ${e.message}`); });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const onHash = () => { const id = hashCase(); if (id && id !== caseIdRef.current) void chooseCaseRef.current(id); };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

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
    autoOpen.current = null;
    if (caseIdRef.current) { setCaseId(null); writeHash(null); }
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



  const source = result ? result.provenance[sourceIndex('series', result) ?? -1]?.source : undefined;

  return <div className="shell">
    <div className="panel">
      <header className="mark">
        <h1>Earth Verdict</h1>
        <p>What is changing on Earth, where, how fast, and how sure we can be. NASA data{result ? `, ${result.case.start_year}–${result.case.end_year}` : ''}.</p>
        <button className="help-button" type="button" onClick={() => setHelp(v => !v)} aria-expanded={help}>How to use <span aria-hidden="true">?</span></button>
        <div className="mode-tabs" role="tablist" aria-label="What to explore">{modes.map(([id, label]) => <button key={id} type="button" role="tab" aria-selected={mode === id} onClick={() => setMode(id)}>{label}</button>)}</div>
      </header>
      <main className="panel-body">
        {help && <section className="tutorial" aria-label="Quick tutorial"><h2>Your first check</h2><ol><li><strong>Choose your case.</strong> Set a place, variable, season, years and direction.</li><li><strong>Run the check.</strong> Read the verdict, rate of change and station status.</li><li><strong>Explore the evidence.</strong> Open “How we checked this” for every number, or “Data sources” for provenance.</li></ol><p>“Not proven” means evidence is insufficient; it does not mean there is no change.</p><button type="button" className="text-button" onClick={() => setHelp(false)}>Got it · close guide</button></section>}
        {mode === 'claims' ? <div className="investigation-panel">
        <div className={`mode-banner ${isLive ? 'live' : ''}`}><div><span className="eyebrow">{isLive ? 'Connected mode' : 'Shared backend snapshots'}</span><p>{isLive ? 'Checks are sent to your backend. No synthetic fallback.' : 'Real observations · provisional statistics. Choose a case to explore the team’s JSON response.'}</p></div><a href={isLive ? './' : 'https://github.com/tByte97/Earth-Verdict-Overflowers/tree/main/data/cases'}>{isLive ? 'Open saved cases' : 'View shared JSON'} <span aria-hidden="true">↗</span></a></div>
        <aside className="case-panel" aria-labelledby="case-heading">
          <div className="panel-heading"><span className="step">01</span><div><p className="eyebrow">Your investigation</p><h2 id="case-heading">Open a case</h2></div></div>
          <div className="cases" role="group" aria-label="Cases">{cases.map(item => {
            const loaded = caseResults[item.id];
            return <button key={item.id} type="button" className="case" data-case={item.id} aria-pressed={caseId === item.id} onClick={() => void chooseCase(item.id)}>
              <b>{item.claim_text}</b>{loaded && loaded !== 'error' && <span>{loaded.variable.label} · {seasonName(loaded.case.season)}</span>}
            </button>;
          })}</div>
          {casesError && <p className="field-help" role="status">{casesError}</p>}
          <details className="case-parameters" open={!result}><summary>Check your own claim</summary>
          <form onSubmit={submit}>
            <label>Claim<input required value={spec.claim_text} onChange={e => edit({ claim_text: e.target.value })} /></label>
            <p className="field-help">The structured parameters below define the actual check. Saved wording comes from the backend response.</p>
            <label>Place<input required value={query} autoComplete="off" onChange={e => { setQuery(e.target.value); setSelectedPlace(false); edit({}); }} aria-describedby="place-status" /></label>
            <p className="field-help" id="place-status" role="status">{selectedPlace ? 'Place selected. Type to search for another.' : searchStatus || 'Type at least two characters, then select a result.'}</p>
            {picked && <p className="field-help" role="status">Picked coordinates: {picked.lat.toFixed(2)}, {picked.lon.toFixed(2)}</p>}
            {places.length > 0 && <ul className="place-results" aria-label="Place search results">{places.map(place => <li key={place.place_id}><button type="button" onClick={() => { edit({ place }); setQuery(place.name); setSelectedPlace(true); setPlaces([]); setPicked(null); flyTo('', placeView(place)); }}>{place.name}</button></li>)}</ul>}
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
          {result ? <ErrorBoundary key={JSON.stringify(result.case) + result.verdict}><VerdictCard result={result} saved={!isLive} /><Explain kind="check" result={result} /></ErrorBoundary> : <div className="empty-state"><span aria-hidden="true">◎</span><h2>{busy ? 'Checking the evidence…' : 'Ready when you are.'}</h2><p>{busy ? 'Waiting for a response from the backend.' : 'Set your parameters and select “Check claim”. Your result will appear here.'}</p></div>}
        </section>
        </div> : <p className="panel-note">Choose “Climate claims” to return to the globe.</p>}
      </main>
      <footer className="credits">
        <p>Data: <a href="https://power.larc.nasa.gov/" target="_blank" rel="noreferrer">NASA POWER</a> (MERRA-2 reanalysis), <a href="https://www.ncei.noaa.gov/" target="_blank" rel="noreferrer">NOAA NCEI</a> stations and <a href="https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/" target="_blank" rel="noreferrer">Climate at a Glance</a>, <a href="https://www.nccs.nasa.gov/services/data-collections/land-based-products/nex-gddp-cmip6" target="_blank" rel="noreferrer">NEX-GDDP-CMIP6</a> scenarios.</p>
        <p>Imagery: NASA Blue Marble and Black Marble via <a href="https://www.earthdata.nasa.gov/gibs" target="_blank" rel="noreferrer">GIBS</a>. Map: <a href="https://maplibre.org/" target="_blank" rel="noreferrer">MapLibre GL JS</a>.</p>
        <p>Earth Verdict · Team Overflowers. Past observations describe evidence about change. They are not a forecast.</p>
      </footer>
    </div>
    <section className="stage" aria-label={mode === 'claims' ? 'Case location' : modes.find(([id]) => id === mode)![1]}>
      <div className="stage-globe" hidden={mode !== 'claims'}>
        <ErrorBoundary><Suspense fallback={<div className="map-loading" role="status">Loading globe…</div>}><Globe place={selectedPlace && !spec.place.place_id.startsWith('region:') ? spec.place : null} destination={destination} station={result?.witness?.station ?? null} onPick={point => {
          const place = pointPlace(point);
          setPicked(point); setSelectedPlace(true); setQuery(place.name);
          edit({ place });
        }} /></Suspense></ErrorBoundary>
        <div className="stage-legend"><span><i className="legend-place" />Case point</span><span><i className="legend-station" />Ground station</span></div>
        <div className="stage-title">
          {result && <div className="eyebrow">{seasonName(result.case.season)} · {result.case.start_year}–{result.case.end_year}{source ? ` · ${source}` : ''}</div>}
          <div className="big">Where is {result ? result.variable.label.toLowerCase() : 'the climate'} changing?</div>
          <div className="src">{selectedPlace ? spec.place.name : 'Choose a place or pick a point'}</div>
        </div>
      </div>
      {mode === 'events' && <div className="stage-workspace legacy-light"><ErrorBoundary><Suspense fallback={<div className="empty-state" role="status">Loading…</div>}><EventsWorkspace /></Suspense></ErrorBoundary></div>}
      {mode === 'co2' && <div className="stage-workspace legacy-light"><ErrorBoundary><Suspense fallback={<div className="empty-state" role="status">Loading…</div>}><Co2Calculator /></Suspense></ErrorBoundary></div>}
    </section>
  </div>;
}

createRoot(document.getElementById('root')!).render(<StrictMode><ErrorBoundary><App /></ErrorBoundary></StrictMode>);
