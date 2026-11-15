import { StrictMode, Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { demoCases, findPlaces, getCase, getCases, getVariables, isLive, isTransient, nearestCase, parseClaim, runCheck, type CaseItem } from './api';
import { VerdictCard } from './VerdictCard';
import { ErrorBoundary } from './ErrorBoundary';
import { CaseSpecSchema } from './schema';
import type { CaseSpec, CheckResult, Place, Variable } from './types';
import { pointPlace, type PickedPoint } from './globe/place';
import { seasonName, seasons, sourceIndex } from './format';
import { caseView, placeView, type Destination } from './globe/camera';
import { parseHash, writeHash } from './url';
import { loadLayerIndex, loadTrendLayer, type LayerEntry, type TrendLayer } from './globe/trends';
import { LayerControls, PairCallout, TrendCaption, TrendLegend, trendView, type LayerKey } from './globe/TrendMap';
import { seasonName as layerSeason } from './globe/presentation';
import './styles.css';
import { Explain } from './events/Explain';
import { CaseFile } from './CaseFile';

const EventsWorkspace = lazy(() => import('./events/EventsWorkspace').then(m => ({ default: m.EventsWorkspace })));
const Co2Calculator = lazy(() => import('./events/Co2Calculator').then(m => ({ default: m.Co2Calculator })));
type Mode = 'claims' | 'events' | 'co2';
const modes: [Mode, string][] = [['claims', 'Climate claims'], ['events', 'Pollution events'], ['co2', 'CO₂ calculator']];
const initialMode = (): Mode => { const m = new URLSearchParams(window.location.search).get('mode'); return m === 'events' || m === 'co2' ? m : 'claims'; };

const DIRECTION_WORD: Record<CaseSpec['claim_direction'], string> = { increase: 'is it increasing?', decrease: 'is it decreasing?', change: 'is it changing either way?' };

const Globe = lazy(() => import('./globe/Globe').then(module => ({ default: module.Globe })));


const hashCase = () => { const state = parseHash(window.location.hash); return state?.kind === 'case' ? state.id : null; };
const hashSpot = () => { const state = parseHash(window.location.hash); return state?.kind === 'spot' ? state : null; };
const savedResults = (): Record<string, CheckResult | 'error'> => isLive ? {} : Object.fromEntries(demoCases.map(item => [item.id, item.result]));

function App() {
  const initial = demoCases.find(item => item.id === hashCase()) ?? demoCases[0];
  // A picked-spot link is restored once the variables are known; until then no case opens.
  const linkedSpot = useRef(hashSpot());
  const startWithCase = !isLive && !linkedSpot.current;
  const [demoId, setDemoId] = useState(initial.id);
  const [spec, setSpec] = useState<CaseSpec>(isLive ? { claim_text: '', variable_id: '', place: { place_id: '', name: '', lat: 0, lon: 0 }, season: 'year', start_year: 1981, end_year: 2025, claim_direction: 'change' } : initial.result.case);
  const [result, setResult] = useState<CheckResult | null>(startWithCase ? initial.result : null);
  const [resultSaved, setResultSaved] = useState(true);
  const [notice, setNotice] = useState('');
  const [variables, setVariables] = useState<Variable[]>(isLive ? [] : [initial.result.variable]);
  const [query, setQuery] = useState(isLive ? '' : initial.result.case.place.name);
  const [places, setPlaces] = useState<Place[]>([]);
  const [selectedPlace, setSelectedPlace] = useState(!isLive);
  const [searchStatus, setSearchStatus] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState<'initial' | 'edited' | 'loading' | 'success' | 'error'>(startWithCase ? 'success' : 'initial');
  const [catalogueLoading, setCatalogueLoading] = useState(true);
  const [help, setHelp] = useState(false);
  // The claim text the current parameters were built for (a case, a map spot or a reading of the claim).
  // New text with untouched parameters is read first, so a verdict never sits under a claim it did not test.
  const [paramsFor, setParamsFor] = useState(isLive ? '' : initial.result.case.claim_text);
  const [manual, setManual] = useState(false);
  const [reading, setReading] = useState(false);
  const [readNotes, setReadNotes] = useState<string[]>([]);
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
  const [caseId, setCaseId] = useState<string | null>(startWithCase ? initial.id : null);
  const flightKey = useRef(1);
  const [destination, setDestination] = useState<Destination | null>(!startWithCase ? null : { key: 1, title: initial.result.case.claim_text, view: caseView(initial.result) });
  // In live mode the first case (or the linked one) opens as soon as it arrives, unless the user acted first.
  const autoOpen = useRef<string | null>(null);

  function flyTo(title: string, view: Destination['view']) { setDestination({ key: ++flightKey.current, title, view }); }
  function openCase(id: string, next: CheckResult) {
    autoOpen.current = null; request.current?.abort(); setBusy(false);
    setDemoId(id); setCaseId(id); setSpec(next.case); setParamsFor(next.case.claim_text); setManual(false); setReadNotes([]); setQuery(next.case.place.name); setSelectedPlace(true); setPicked(null);
    setPickNote(''); setError(''); setNotice(''); setResult(next); setResultSaved(!isLive); setPhase('success');
    setLayerKey({ variable_id: next.case.variable_id, season: String(next.case.season) });
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
      autoOpen.current = linkedSpot.current ? null : items.find(item => item.id === hashCase())?.id ?? items[0]?.id ?? null;
      // All cases load in parallel; each button gets its subtitle when its response arrives.
      for (const item of items) getCase(item.id, controller.signal).then(next => {
        setCaseResults(current => ({ ...current, [item.id]: next }));
        if (autoOpen.current === item.id) openCase(item.id, next);
      }).catch(() => { if (!controller.signal.aborted) setCaseResults(current => ({ ...current, [item.id]: 'error' })); });
    }).catch(e => { if (!controller.signal.aborted) setCasesError(`Saved cases are unavailable: ${e.message}`); });
    return () => controller.abort();
  }, []);

  // Trend map: the index lists the layers that exist (null = no index yet, show only the case's layer).
  const [layerIndex, setLayerIndex] = useState<LayerEntry[] | null>(null);
  const [layerKey, setLayerKey] = useState<LayerKey | null>(isLive ? null : { variable_id: initial.result.case.variable_id, season: String(initial.result.case.season) });
  const [layer, setLayer] = useState<TrendLayer | null>(null);
  const [layerStatus, setLayerStatus] = useState('');
  const [fade, setFade] = useState(true);
  const [pickNote, setPickNote] = useState('');
  const view = useMemo(() => (layer ? trendView(layer) : null), [layer]);
  const labelOf = (variableId: string) => variables.find(variable => variable.id === variableId)?.label ?? variableId;

  useEffect(() => {
    const controller = new AbortController();
    loadLayerIndex(controller.signal).then(index => {
      if (controller.signal.aborted) return;
      setLayerIndex(index);
      if (index?.length) setLayerKey(current => current ?? { variable_id: index[0].variable_id, season: index[0].season });
    }).catch(() => { if (!controller.signal.aborted) setLayerIndex(null); });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const onHash = () => { const id = hashCase(); if (id && id !== caseIdRef.current) void chooseCaseRef.current(id); };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  useEffect(() => {
    setLayer(null);
    if (!layerKey) { setLayerStatus(''); return; }
    const controller = new AbortController();
    setLayerStatus('Loading the trend map…');
    loadTrendLayer(layerKey.variable_id, layerKey.season, controller.signal).then(next => {
      if (controller.signal.aborted) return;
      setLayer(next); setLayerStatus(next ? '' : `No trend map for ${labelOf(layerKey.variable_id).toLowerCase()} in this season yet.`);
    }).catch(e => { if (!controller.signal.aborted) setLayerStatus(`Trend map unavailable: ${e.message}`); });
    return () => controller.abort();
  }, [layerKey]);

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
    setCaseId(null); writeHash(null);
    request.current?.abort(); setBusy(false); setError(''); setNotice(''); setResult(null); setPhase('edited'); setSpec(current => ({ ...current, ...next }));
  }
  function editParams(next: Partial<CaseSpec>) { edit(next); setManual(true); }
  const needsReading = isLive && spec.claim_text.trim().length >= 3 && spec.claim_text !== paramsFor && !manual;

  async function readClaim() {
    autoOpen.current = null; setCaseId(null); writeHash(null); request.current?.abort();
    const text = spec.claim_text;
    setReading(true); setError(''); setNotice(''); setResult(null); setPhase('edited'); setReadNotes([]);
    try {
      const parsed = await parseClaim(text);
      setSpec(parsed.spec); setParamsFor(text); setManual(false); setReadNotes(parsed.notes); setPicked(null); setPlaces([]);
      if (parsed.place_found) { setQuery(parsed.spec.place.name); setSelectedPlace(true); flyTo('', placeView(parsed.spec.place)); }
      else { setQuery(parsed.place_query ?? ''); setSelectedPlace(false); }
    } catch (e) {
      // The fields stay as they are; the next press checks them as set.
      setManual(true);
      setError(`${e instanceof Error ? e.message : 'Could not read the claim.'} Set the parameters below by hand, then select “Check claim”.`); setPhase('error');
    } finally { setReading(false); }
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
    setPickNote('');
    // The map follows the case being checked, when a layer exists for it.
    if (!layerIndex || layerIndex.some(entry => entry.variable_id === spec.variable_id && entry.season === String(spec.season))) setLayerKey({ variable_id: spec.variable_id, season: String(spec.season) });
    await check(spec);
  }

  async function check(next: CaseSpec) {
    request.current?.abort(); const controller = new AbortController(); request.current = controller;
    setBusy(true); setPhase('loading'); setResult(null); setError(''); setNotice('');
    try { const response = await runCheck(next, demoId, controller.signal); if (!controller.signal.aborted) { setResult(response); setResultSaved(!isLive); setPhase('success'); } }
    catch (e) {
      if (controller.signal.aborted) return;
      if (isLive && isTransient(e)) {
        // Busy, rate-limited, timed out or unreachable: show real saved data instead of an empty screen.
        const near = nearestCase(next.place);
        setNotice(`Live service busy — showing a saved NASA snapshot: ${near.label}.`);
        setResult(near.result); setResultSaved(true); setPhase('success');
      } else { setError(e instanceof Error ? e.message : 'The check failed. Please try again.'); setPhase('error'); }
    }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }

  // A map click checks that spot right away with the layer's variable, season and period.
  // Without a layer the form's current choices are used. The question is always "is it changing?".
  function checkPoint(point: PickedPoint, key = layerKey) {
    if (!isLive) { setPickNote('Checking a new spot needs the backend. Saved mode covers the saved cases only.'); return; }
    const entry = (layer && key && layer.variable_id === key.variable_id && layer.season === key.season ? layer : null)
      ?? layerIndex?.find(item => key && item.variable_id === key.variable_id && item.season === key.season);
    checkSpot(point, entry?.variable_id ?? spec.variable_id, CaseSpecSchema.shape.season.parse(entry?.season ?? spec.season), entry?.start_year ?? spec.start_year, entry?.end_year ?? spec.end_year);
  }

  // Checks one spot and writes it to the URL. A restored link also flies there; saved mode only shows the spot.
  function checkSpot(point: PickedPoint, variableId: string, season: CaseSpec['season'], start: number, end: number, restored = false) {
    if (!variables.some(variable => variable.id === variableId)) { setPhase('error'); setError('Select an available backend variable.'); return; }
    const place = pointPlace(point);
    const subject = season === 'year' ? labelOf(variableId).toLowerCase() : `${layerSeason(String(season)).toLowerCase()} ${labelOf(variableId).toLowerCase()}`;
    const next: CaseSpec = { claim_text: `Is ${subject} changing at ${place.name}?`, variable_id: variableId, place, season, start_year: start, end_year: end, claim_direction: 'change' };
    autoOpen.current = null; setCaseId(null); setParamsFor(next.claim_text); setManual(false); setReadNotes([]);
    setPicked(point); setSelectedPlace(true); setQuery(place.name); setPlaces([]); setSpec(next);
    if (restored) { setLayerKey({ variable_id: variableId, season: String(season) }); flyTo('', placeView(place)); }
    writeHash({ kind: 'spot', variable: variableId, season, start, end, lon: point.lon, lat: point.lat });
    if (!isLive) { setResult(null); setPhase('initial'); setPickNote('Checking a new spot needs the backend. Saved mode covers the saved cases only.'); return; }
    setPickNote('');
    void check(next);
  }
  const checkSpotRef = useRef(checkSpot);
  checkSpotRef.current = checkSpot;
  useEffect(() => {
    const spot = linkedSpot.current;
    if (catalogueLoading || !spot) return;
    linkedSpot.current = null;
    checkSpotRef.current({ lat: spot.lat, lon: spot.lon }, spot.variable, spot.season, spot.start, spot.end, true);
  }, [catalogueLoading]);

  // Changing the layer keeps the picked spot and checks it again with the new layer.
  function chooseLayer(key: LayerKey) {
    setLayerKey(key);
    if (picked && isLive) checkPoint(picked, key);
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
        <div className={`mode-banner ${isLive ? 'live' : ''}`}><div><span className="eyebrow">{isLive ? 'Connected mode' : 'Shared backend snapshots'}</span><p>{isLive ? 'Checks are sent to your backend. No synthetic fallback.' : 'Real NASA and NOAA observations. Choose a case to explore the team’s JSON response.'}</p></div><a href={isLive ? './' : 'https://github.com/tByte97/Earth-Verdict-Overflowers/tree/main/data/cases'}>{isLive ? 'Open saved cases' : 'View shared JSON'} <span aria-hidden="true">↗</span></a></div>
        <section className="trend-panel" aria-labelledby="trend-heading">
          <h2 id="trend-heading">Trend map</h2>
          <LayerControls index={layerIndex} value={layerKey} onChange={chooseLayer} fade={fade} onFade={setFade} labelOf={labelOf} />
          {pickNote && <p className="trend-note" role="status">{pickNote}</p>}
          {view && <PairCallout view={view} variableLabel={labelOf(view.layer.variable_id)} />}
        </section>
        <aside className="case-panel" aria-labelledby="case-heading">
          <div className="panel-heading"><span className="step">01</span><div><p className="eyebrow">Your investigation</p><h2 id="case-heading">Open a case</h2></div></div>
          <div className="cases" role="group" aria-label="Cases">{cases.map(item => {
            const loaded = caseResults[item.id];
            return <button key={item.id} type="button" className="case" data-case={item.id} aria-pressed={caseId === item.id} onClick={() => void chooseCase(item.id)}>
              <b>{item.claim_text}</b>{loaded && loaded !== 'error' && <span>{loaded.variable.label} · {seasonName(loaded.case.season)}</span>}
            </button>;
          })}</div>
          {casesError && <p className="field-help" role="status">{casesError}</p>}
          {notice && <p className="data-note notice" role="status">{notice}</p>}
          <details className="case-parameters" open={!result}><summary>Check your own claim</summary>
          <form onSubmit={submit}>
            <label>Claim<input required maxLength={300} value={spec.claim_text} onChange={e => edit({ claim_text: e.target.value })} onKeyDown={e => { if (e.key === 'Enter' && needsReading) { e.preventDefault(); void readClaim(); } }} /></label>
            <p className="field-help">{isLive ? 'Write the claim in any language and select “Read claim”: the fields below fill in, and you confirm them before the check.' : 'The structured parameters below define the actual check. Saved wording comes from the backend response.'}</p>
            {isLive && !needsReading && spec.claim_text.trim().length >= 3 && <button type="button" className="text-button" disabled={reading || busy} onClick={() => void readClaim()}>Read the claim again</button>}
            {readNotes.length > 0 && <ul className="field-help read-notes" aria-label="What was assumed">{readNotes.map(note => <li key={note}>{note}</li>)}</ul>}
            <label>Place<input required value={query} autoComplete="off" onChange={e => { setQuery(e.target.value); setSelectedPlace(false); editParams({}); }} aria-describedby="place-status" /></label>
            <p className="field-help" id="place-status" role="status">{selectedPlace ? 'Place selected. Type to search for another.' : searchStatus || 'Type at least two characters, then select a result.'}</p>
            {picked && <p className="field-help" role="status">Picked coordinates: {picked.lat.toFixed(2)}, {picked.lon.toFixed(2)}</p>}
            {places.length > 0 && <ul className="place-results" aria-label="Place search results">{places.map(place => <li key={place.place_id}><button type="button" onClick={() => { editParams({ place }); setQuery(place.name); setSelectedPlace(true); setPlaces([]); setPicked(null); flyTo('', placeView(place)); }}>{place.name}</button></li>)}</ul>}
            <label>Variable<select required value={spec.variable_id} disabled={catalogueLoading || !variables.length} onChange={e => editParams({ variable_id: e.target.value })}>{!variables.length && <option value="">{catalogueLoading ? 'Loading variables…' : 'No variables available'}</option>}{variables.map(v => <option key={v.id} value={v.id}>{v.label} · {v.units}</option>)}</select></label>
            {variables.find(v => v.id === spec.variable_id)?.definition && <p className="field-help">{variables.find(v => v.id === spec.variable_id)!.definition}</p>}
            <label>Season<select value={spec.season} onChange={e => editParams({ season: CaseSpecSchema.shape.season.parse(/^\d+$/.test(e.target.value) ? Number(e.target.value) : e.target.value) })}>{seasons.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <fieldset><legend>Observation period</legend><div className="year-fields"><label>From<input type="number" required min="1" max="9999" value={Number.isNaN(spec.start_year) ? '' : spec.start_year} onChange={e => editParams({ start_year: e.target.valueAsNumber })} /></label><span aria-hidden="true">—</span><label>To<input type="number" required min="1" max="9999" value={Number.isNaN(spec.end_year) ? '' : spec.end_year} onChange={e => editParams({ end_year: e.target.valueAsNumber })} /></label></div></fieldset>
            <label>Claim direction<select value={spec.claim_direction} onChange={e => editParams({ claim_direction: e.target.value as CaseSpec['claim_direction'] })}><option value="increase">Increasing</option><option value="decrease">Decreasing</option><option value="change">Changing in either direction</option></select></label>
            {!needsReading && selectedPlace && variables.some(v => v.id === spec.variable_id) && <p className="will-test" role="status"><b>This check will test:</b> {labelOf(spec.variable_id).toLowerCase()} · {spec.place.name} · {seasonName(spec.season).toLowerCase()} · {spec.start_year}–{spec.end_year} · {DIRECTION_WORD[spec.claim_direction]}</p>}
            {error && <div className="error" role="alert">{error}</div>}
            <button className="primary-button" type={needsReading ? 'button' : 'submit'} onClick={needsReading ? () => void readClaim() : undefined} disabled={busy || reading || catalogueLoading || !variables.length}>{reading ? 'Reading the claim…' : busy ? 'Checking…' : needsReading ? 'Read claim' : 'Check claim'} <span aria-hidden="true">→</span></button>
            <p className="field-help">{isLive ? 'Your backend performs the calculations.' : 'Saved cases return the team’s JSON unchanged. Custom periods require the calculation API.'}</p>
          </form>
          </details>
        </aside>
        <section className="result-panel" aria-label="Check result" aria-busy={busy}>
          <div className="result-heading"><span className="step">02</span><p className="eyebrow">The evidence, in focus</p></div>
          <div id="result-status" role="status" aria-live="polite" aria-atomic="true" className="sr-only">{phase === 'loading' ? 'Check in progress.' : phase === 'error' ? `Check unavailable. ${error}` : phase === 'success' && result ? `Result: ${result.verdict.replace('_', ' ')}.` : phase === 'edited' ? 'Parameters changed. Run a check to see the result.' : catalogueLoading ? 'Loading available variables.' : 'Ready to configure a check.'}</div>
          {result ? <ErrorBoundary key={JSON.stringify(result.case) + result.verdict}><VerdictCard result={result} saved={resultSaved} /><Explain kind="check" result={result} /><CaseFile result={result} /></ErrorBoundary> : <div className="empty-state"><span aria-hidden="true">◎</span><h2>{busy ? 'Checking the evidence…' : 'Ready when you are.'}</h2><p>{busy ? 'Fetching satellite records and the nearest weather station. A new place can take up to a minute.' : 'Set your parameters and select “Check claim”. Your result will appear here.'}</p></div>}
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
        <ErrorBoundary><Suspense fallback={<div className="map-loading" role="status">Loading globe…</div>}><Globe place={selectedPlace && !spec.place.place_id.startsWith('region:') ? spec.place : null} destination={destination} station={result?.witness?.station ?? null} trend={view} fade={fade} onPick={point => checkPoint(point)} /></Suspense></ErrorBoundary>
        <div className="stage-legend">
          {view && <TrendLegend view={view} fade={fade} variableLabel={labelOf(view.layer.variable_id)} />}
          <div className="stage-legend-markers"><span><i className="legend-place" />Case point</span><span><i className="legend-station" />Ground station</span></div>
        </div>
        <div className="stage-title">
          {/* With a trend layer on the map, the title describes that layer. */}
          {layer ? <>
            <div className="eyebrow">{layerSeason(layer.season)} · {layer.start_year}–{layer.end_year}</div>
            <div className="big">Where is {labelOf(layer.variable_id).toLowerCase()} changing?</div>
          </> : <>
            {result && <div className="eyebrow">{seasonName(result.case.season)} · {result.case.start_year}–{result.case.end_year}{source ? ` · ${source}` : ''}</div>}
            <div className="big">Where is {result ? result.variable.label.toLowerCase() : 'the climate'} changing?</div>
          </>}
          <div className="src">{selectedPlace ? spec.place.name : 'Choose a place or pick a point'}</div>
          {layer && <TrendCaption layer={layer} />}
          {layerStatus && <p className="trend-status" role="status">{layerStatus}</p>}
        </div>
      </div>
      {mode === 'events' && <div className="stage-workspace"><ErrorBoundary><Suspense fallback={<div className="empty-state" role="status">Loading…</div>}><EventsWorkspace /></Suspense></ErrorBoundary></div>}
      {mode === 'co2' && <div className="stage-workspace"><ErrorBoundary><Suspense fallback={<div className="empty-state" role="status">Loading…</div>}><Co2Calculator /></Suspense></ErrorBoundary></div>}
    </section>
  </div>;
}

createRoot(document.getElementById('root')!).render(<StrictMode><ErrorBoundary><App /></ErrorBoundary></StrictMode>);
