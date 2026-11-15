import { StrictMode, Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { FALLBACK_REGIONS, demoCases, findPlaces, getCase, getCases, getRegions, getVariables, isLive, isTransient, nearestCase, parseClaim, runCheck, type CaseItem } from './api';
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
import { describe, firstIndex, frameOf, loadYearMap, yearView, type YearMap } from './globe/years';
import { Timeline, YearLegend } from './globe/Timeline';
import './styles.css';
import { CaseFile } from './CaseFile';

const EventsWorkspace = lazy(() => import('./events/EventsWorkspace').then(m => ({ default: m.EventsWorkspace })));
const Co2Calculator = lazy(() => import('./events/Co2Calculator').then(m => ({ default: m.Co2Calculator })));
type Mode = 'claims' | 'events' | 'co2';
const modes: [Mode, string][] = [['claims', 'Climate claims'], ['events', 'Pollution events'], ['co2', 'CO₂ calculator']];
const initialMode = (): Mode => { const m = new URLSearchParams(window.location.search).get('mode'); return m === 'events' || m === 'co2' ? m : 'claims'; };

const DIRECTION_WORD: Record<CaseSpec['claim_direction'], string> = { increase: 'is it increasing?', decrease: 'is it decreasing?', change: 'is it changing either way?' };
const savedPlacesSummary = [...new Set(demoCases.map(item => item.result.case.place.name))].join('; ');

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
  const [regions, setRegions] = useState<Place[]>(FALLBACK_REGIONS);
  const regionsLoaded = useRef(false);
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
    // Back to the claims: the globe returns to the open case.
    if (m === 'claims' && mode !== 'claims' && result) flyTo(result.case.claim_text, caseView(result));
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
  const userActed = useRef(false);

  function flyTo(title: string, view: Destination['view']) { setDestination({ key: ++flightKey.current, title, view }); }
  // Events and CO₂ put their controls in the left panel and their headline over the globe; the globe shows
  // the event's place, or the whole planet for CO₂.
  const [panelSlot, setPanelSlot] = useState<HTMLElement | null>(null);
  const [stageSlot, setStageSlot] = useState<HTMLElement | null>(null);
  const [modePlace, setModePlace] = useState<Place | null>(null);
  const [eventPick, setEventPick] = useState<{ point: PickedPoint; key: number } | null>(null);
  const showOnGlobe = useCallback((place: Place, title: string) => { setModePlace(place); setDestination({ key: ++flightKey.current, title, view: placeView(place) }); }, []);
  const showPlanet = useCallback(() => { setModePlace(null); setDestination({ key: ++flightKey.current, title: 'The whole planet', view: { kind: 'globe' } }); }, []);
  function openCase(id: string, next: CheckResult) {
    autoOpen.current = null; userActed.current = true; request.current?.abort(); setBusy(false);
    setDemoId(id); setCaseId(id); setSpec(next.case); setParamsFor(next.case.claim_text); setManual(false); setReadNotes([]); setQuery(next.case.place.name); setSelectedPlace(true); setPicked(null);
    setPickNote(''); setError(''); setNotice(''); setResult(next); setResultSaved(!isLive); setPhase('success');
    syncCaseLayer(next.case.variable_id, String(next.case.season), next.variable.label);
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
      autoOpen.current = (userActed.current || linkedSpot.current) ? null : items.find(item => item.id === hashCase())?.id ?? items[0]?.id ?? null;
      // All cases load in parallel; each button gets its subtitle when its response arrives.
      for (const item of items) getCase(item.id, controller.signal).then(next => {
        setCaseResults(current => ({ ...current, [item.id]: next }));
        if (autoOpen.current === item.id) openCase(item.id, next);
      }).catch(() => { if (!controller.signal.aborted) setCaseResults(current => ({ ...current, [item.id]: 'error' })); });
    }).catch(e => { if (!controller.signal.aborted) setCasesError(`Saved cases are unavailable: ${e.message}`); });
    return () => controller.abort();
  }, []);

  // Trend map: undefined = index loading, array = available layers, null = backend has no index.
  const [layerIndex, setLayerIndex] = useState<LayerEntry[] | null | undefined>(undefined);
  const layerIndexRef = useRef(layerIndex);
  layerIndexRef.current = layerIndex;
  const [layerKey, setLayerKey] = useState<LayerKey | null>(null);
  const [layer, setLayer] = useState<TrendLayer | null>(null);
  const [layerStatus, setLayerStatus] = useState('');
  const [layerNote, setLayerNote] = useState('');
  const pendingLayer = useRef<{ variable_id: string; season: string; variableLabel?: string } | null>(
    startWithCase ? { variable_id: initial.result.case.variable_id, season: String(initial.result.case.season), variableLabel: initial.result.variable.label } : null,
  );
  const [fade, setFade] = useState(true);
  const [pickNote, setPickNote] = useState('');
  const view = useMemo(() => (layer ? trendView(layer) : null), [layer]);
  // Timeline: the same variable and season as the trend layer, one map per year. A picked year replaces the
  // trend map on the globe; null shows the whole-period trend again.
  const [yearMap, setYearMap] = useState<YearMap | null>(null);
  const [timelineYear, setTimelineYear] = useState<number | null>(null);
  const [smooth, setSmooth] = useState(false);
  const years = useMemo(() => (yearMap && layer && yearMap.variable_id === layer.variable_id && yearMap.season === layer.season ? yearView(yearMap) : null), [yearMap, layer]);
  const frame = useMemo(() => {
    if (!years || timelineYear === null) return null;
    const index = years.map.years.indexOf(timelineYear);
    return frameOf(years, Math.max(firstIndex(years, smooth), index < 0 ? years.map.years.length - 1 : index), smooth);
  }, [years, timelineYear, smooth]);
  const yearsRef = useRef(years);
  yearsRef.current = years;
  const pickYear = useCallback((index: number | null) => setTimelineYear(index === null ? null : yearsRef.current?.map.years[index] ?? null), []);
  const labelOf = (variableId: string) => variables.find(variable => variable.id === variableId)?.label ?? variableId;

  function missingLayerNote(variableId: string, season: string, variableLabel?: string) {
    const varName = (variableLabel ?? labelOf(variableId)).toLowerCase();
    const parsedSeason = CaseSpecSchema.shape.season.safeParse(/^\d+$/.test(season) ? Number(season) : season);
    const seasonLabel = seasonName(parsedSeason.success ? parsedSeason.data : 'year').toLowerCase();
    return `No trend map for ${varName} (${seasonLabel}). Trend maps cover air temperature and precipitation over Ukraine, for the year, summer and winter.`;
  }

  function syncCaseLayer(variableId: string, season: string, variableLabel?: string) {
    const currentIndex = layerIndexRef.current;
    if (currentIndex === undefined) {
      pendingLayer.current = { variable_id: variableId, season, variableLabel };
      return;
    }
    pendingLayer.current = null;
    if (currentIndex === null) {
      if (['air_temp', 'precip'].includes(variableId) && ['year', 'JJA', 'DJF'].includes(season)) {
        setLayerNote('');
        setLayerKey({ variable_id: variableId, season });
      } else {
        setLayerNote(missingLayerNote(variableId, season, variableLabel));
      }
      return;
    }
    if (currentIndex.some(entry => entry.variable_id === variableId && entry.season === season)) {
      setLayerNote('');
      setLayerKey({ variable_id: variableId, season });
    } else {
      setLayerNote(missingLayerNote(variableId, season, variableLabel));
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    loadLayerIndex(controller.signal).then(index => {
      if (controller.signal.aborted) return;
      setLayerIndex(index);
      const pending = pendingLayer.current;
      pendingLayer.current = null;
      if (index?.length) {
        if (pending && index.some(entry => entry.variable_id === pending.variable_id && entry.season === pending.season)) {
          setLayerNote('');
          setLayerKey({ variable_id: pending.variable_id, season: pending.season });
        } else if (pending) {
          setLayerNote(missingLayerNote(pending.variable_id, pending.season, pending.variableLabel));
        } else {
          setLayerKey(current => current ?? { variable_id: index[0].variable_id, season: index[0].season });
        }
      } else if (pending) {
        if (['air_temp', 'precip'].includes(pending.variable_id) && ['year', 'JJA', 'DJF'].includes(pending.season)) {
          setLayerNote('');
          setLayerKey({ variable_id: pending.variable_id, season: pending.season });
        } else {
          setLayerNote(missingLayerNote(pending.variable_id, pending.season, pending.variableLabel));
        }
      }
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
    setYearMap(null);
    if (!layerKey) return;
    const controller = new AbortController();
    // No year-by-year map for this layer is not an error: the timeline is simply not offered.
    loadYearMap(layerKey.variable_id, layerKey.season, controller.signal).then(next => { if (!controller.signal.aborted) setYearMap(next); }).catch(() => {});
    return () => controller.abort();
  }, [layerKey]);

  useEffect(() => {
    const controller = new AbortController();
    getVariables(controller.signal).then(values => {
      if (controller.signal.aborted) return;
      setVariables(values);
      setSpec(current => {
        const chosen = values.find(value => value.id === current.variable_id) ?? values[0];
        if (current.variable_id) return { ...current, variable_id: chosen.id };
        return {
          ...current,
          variable_id: chosen.id,
          start_year: chosen.first_year ?? current.start_year,
          end_year: chosen.last_year ?? current.end_year,
        };
      });
      setCatalogueLoading(false);
    }).catch(e => {
      if (controller.signal.aborted) return;
      setError(`Cannot load variables: ${e.message}`); setCatalogueLoading(false); setPhase('error');
    });
    return () => { controller.abort(); request.current?.abort(); };
  }, []);

  useEffect(() => {
    if (!isLive || spec.variable_id !== 'global_temp' || regionsLoaded.current) return;
    regionsLoaded.current = true;
    const controller = new AbortController();
    getRegions(controller.signal).then(items => { if (!controller.signal.aborted) setRegions(items); }).catch(() => {});
    return () => controller.abort();
  }, [spec.variable_id]);

  function edit(next: Partial<CaseSpec>) {
    autoOpen.current = null; userActed.current = true;
    setCaseId(null); writeHash(null);
    request.current?.abort(); setBusy(false); setError(''); setNotice(''); setResult(null); setPhase('edited'); setSpec(current => ({ ...current, ...next }));
  }
  function editParams(next: Partial<CaseSpec>) { edit(next); setManual(true); }
  function changeVariable(nextId: string) {
    const nextVar = variables.find(v => v.id === nextId);
    const patch: Partial<CaseSpec> = { variable_id: nextId };
    if (nextVar?.first_year !== undefined && nextVar?.last_year !== undefined) {
      const clamp = (y: number) => Math.min(nextVar.last_year!, Math.max(nextVar.first_year!, Number.isFinite(y) ? y : nextVar.first_year!));
      patch.start_year = clamp(spec.start_year);
      patch.end_year = clamp(spec.end_year);
    }
    if (nextId === 'global_temp') {
      if (!spec.place.place_id.startsWith('region:')) {
        const region = regions[0];
        patch.place = region;
        setQuery(region.name);
        setSelectedPlace(true);
        setPlaces([]);
        setPicked(null);
        flyTo('', placeView(region));
      }
    } else if (spec.place.place_id.startsWith('region:')) {
      patch.place = { place_id: '', name: '', lat: 0, lon: 0 };
      setQuery('');
      setSelectedPlace(false);
      setPlaces([]);
      setPicked(null);
    }
    editParams(patch);
  }
  const needsReading = isLive && spec.claim_text.trim().length >= 3 && spec.claim_text !== paramsFor && !manual;

  async function readClaim() {
    autoOpen.current = null; userActed.current = true; setCaseId(null); writeHash(null); request.current?.abort();
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
    if (!isLive || spec.variable_id === 'global_temp' || selectedPlace || query.trim().length < 2) { setPlaces([]); setSearchStatus(''); return; }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setSearchStatus('Searching…');
      findPlaces(query, controller.signal).then(items => {
        if (!controller.signal.aborted) { setPlaces(items); setSearchStatus(items.length ? 'Select a place below.' : isLive ? 'No places found. Try another name.' : `No places found. Saved cases cover ${savedPlacesSummary}.`); }
      }).catch(e => { if (e.name !== 'AbortError') setSearchStatus(`Search failed: ${e.message}`); });
    }, 250);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [query, selectedPlace, spec.variable_id]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!isLive) return;
    if (!variables.some(variable => variable.id === spec.variable_id)) { setError('Select an available backend variable.'); setPhase('error'); return; }
    if (!selectedPlace) { setPhase('error'); setError('Select a place from the search results first.'); return; }
    if (!Number.isInteger(spec.start_year) || !Number.isInteger(spec.end_year) || spec.start_year > spec.end_year) { setPhase('error'); setError('Choose valid years: the start must not be after the end.'); return; }
    setPickNote('');
    // The map follows the case being checked, when a layer exists for it.
    syncCaseLayer(spec.variable_id, String(spec.season));
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
    if (!isLive && !restored) return;
    if (!variables.some(variable => variable.id === variableId)) { setPhase('error'); setError('Select an available backend variable.'); return; }
    const place = pointPlace(point);
    const subject = season === 'year' ? labelOf(variableId).toLowerCase() : `${layerSeason(String(season)).toLowerCase()} ${labelOf(variableId).toLowerCase()}`;
    const next: CaseSpec = { claim_text: `Is ${subject} changing at ${place.name}?`, variable_id: variableId, place, season, start_year: start, end_year: end, claim_direction: 'change' };
    autoOpen.current = null; userActed.current = true; setCaseId(null); setParamsFor(next.claim_text); setManual(false); setReadNotes([]);
    setPicked(point); setSelectedPlace(true); setQuery(place.name); setPlaces([]); setSpec(next);
    if (restored) { syncCaseLayer(variableId, String(season)); flyTo('', placeView(place)); }
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
    pendingLayer.current = null;
    setLayerNote('');
    setLayerKey(key);
    if (picked && isLive) checkPoint(picked, key);
  }

  const selectedVar = variables.find(v => v.id === spec.variable_id);
  const source = result ? result.provenance[sourceIndex('series', result) ?? -1]?.source : undefined;

  return <div className="shell">
    <div className="panel">
      <header className="mark">
        <div className="brand-row">
          <span className="brand-mark" aria-hidden="true">◉</span>
          <h1>Earth Verdict</h1>
        </div>
        <button className="help-button" type="button" onClick={() => setHelp(v => !v)} aria-expanded={help}>How to use <span aria-hidden="true">?</span></button>
        <p>What is changing on Earth, where, how fast, and how sure we can be. NASA data{mode === 'claims' && result ? `, ${result.case.start_year}–${result.case.end_year}` : ''}.</p>
        <div className="mode-tabs" role="tablist" aria-label="What to explore">{modes.map(([id, label]) => <button key={id} type="button" role="tab" aria-selected={mode === id} onClick={() => setMode(id)}>{label}</button>)}</div>
      </header>
      <main className="panel-body">
        {help && <section className="tutorial" aria-label="Quick tutorial"><h2>Your first check</h2><ol><li><strong>Choose your case.</strong> Set a place, variable, season, years and direction.</li><li><strong>Run the check.</strong> Read the verdict, rate of change and station status.</li><li><strong>Explore the evidence.</strong> Open “How we checked this” for every number, or “Data sources” for provenance.</li></ol><p>“Not proven” means evidence is insufficient; it does not mean there is no change.</p><button type="button" className="text-button" onClick={() => setHelp(false)}>Got it · close guide</button></section>}
        {mode === 'claims' ? <div className="investigation-panel">
        <div className={`mode-banner ${isLive ? 'live' : ''}`}><div><span className="eyebrow">{isLive ? 'Connected mode' : 'Shared backend snapshots'}</span><p>{isLive ? 'Checks are sent to your backend. No synthetic fallback.' : 'Real NASA and NOAA observations. Choose a case to explore the team’s JSON response.'}</p></div><a href={isLive ? '?source=saved' : 'https://github.com/tByte97/Earth-Verdict-Overflowers/tree/main/data/cases'}>{isLive ? 'Open saved cases' : 'View shared JSON'} <span aria-hidden="true">↗</span></a></div>
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
            <label>Claim<input required disabled={!isLive} maxLength={300} value={spec.claim_text} onChange={e => { setManual(false); edit({ claim_text: e.target.value }); }} onKeyDown={e => { if (e.key === 'Enter' && needsReading) { e.preventDefault(); void readClaim(); } }} /></label>
            <p className="field-help">{isLive ? 'Write the claim in any language and select “Read claim”: the fields below fill in, and you confirm them before the check.' : 'Saved mode shows fixed snapshots. Custom checks need the live service.'}</p>
            {isLive && !needsReading && spec.claim_text.trim().length >= 3 && <button type="button" className="text-button" disabled={reading || busy} onClick={() => void readClaim()}>Read the claim again</button>}
            {readNotes.length > 0 && <ul className="field-help read-notes" aria-label="What was assumed">{readNotes.map(note => <li key={note}>{note}</li>)}</ul>}
            {spec.variable_id === 'global_temp' ? <>
              <label>Region<select required disabled={!isLive || catalogueLoading} value={regions.some(r => r.place_id === spec.place.place_id) ? spec.place.place_id : ''} onChange={e => {
                const region = regions.find(r => r.place_id === e.target.value);
                if (!region) return;
                editParams({ place: region }); setQuery(region.name); setSelectedPlace(true); setPlaces([]); setPicked(null); flyTo('', placeView(region));
              }}>{!regions.some(r => r.place_id === spec.place.place_id) && <option value="">Select a region…</option>}{regions.map(r => <option key={r.place_id} value={r.place_id}>{r.name}</option>)}</select></label>
              <p className="field-help">Global and continental land–ocean averages from NOAA.</p>
            </> : <>
              <label>Place<input required disabled={!isLive} value={query} autoComplete="off" onChange={e => { setQuery(e.target.value); setSelectedPlace(false); editParams({}); }} aria-describedby="place-status" /></label>
              <p className="field-help" id="place-status" role="status">{!isLive ? 'Saved place selected.' : selectedPlace ? 'Place selected. Type to search for another.' : searchStatus || 'Type at least two characters, then select a result.'}</p>
              {picked && <p className="field-help" role="status">Picked coordinates: {picked.lat.toFixed(2)}, {picked.lon.toFixed(2)}</p>}
              {places.length > 0 && <ul className="place-results" aria-label="Place search results">{places.map(place => <li key={place.place_id}><button type="button" onClick={() => { editParams({ place }); setQuery(place.name); setSelectedPlace(true); setPlaces([]); setPicked(null); flyTo('', placeView(place)); }}>{place.name}</button></li>)}</ul>}
            </>}
            <label>Variable<select required value={spec.variable_id} disabled={!isLive || catalogueLoading || !variables.length} onChange={e => changeVariable(e.target.value)}>{!variables.length && <option value="">{catalogueLoading ? 'Loading variables…' : 'No variables available'}</option>}{variables.map(v => <option key={v.id} value={v.id}>{v.label} · {v.units}</option>)}</select></label>
            {selectedVar?.definition && <p className="field-help">{selectedVar.definition}</p>}
            <label>Season<select disabled={!isLive} value={spec.season} onChange={e => editParams({ season: CaseSpecSchema.shape.season.parse(/^\d+$/.test(e.target.value) ? Number(e.target.value) : e.target.value) })}>{seasons.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <fieldset><legend>Observation period</legend><div className="year-fields"><label>From<input type="number" required disabled={!isLive} min={selectedVar?.first_year ?? 1} max={selectedVar?.last_year ?? 9999} value={Number.isNaN(spec.start_year) ? '' : spec.start_year} onChange={e => editParams({ start_year: e.target.valueAsNumber })} /></label><span aria-hidden="true">—</span><label>To<input type="number" required disabled={!isLive} min={selectedVar?.first_year ?? 1} max={selectedVar?.last_year ?? 9999} value={Number.isNaN(spec.end_year) ? '' : spec.end_year} onChange={e => editParams({ end_year: e.target.valueAsNumber })} /></label></div><p className="field-help">{selectedVar?.first_year !== undefined && selectedVar?.last_year !== undefined ? `${selectedVar.first_year}–${selectedVar.last_year} · at least 15 years${spec.season === 'DJF' ? ' (winter drops the first year)' : ''}.` : 'At least 15 years.'}</p></fieldset>
            <label>Claim direction<select disabled={!isLive} value={spec.claim_direction} onChange={e => editParams({ claim_direction: e.target.value as CaseSpec['claim_direction'] })}><option value="increase">Increasing</option><option value="decrease">Decreasing</option><option value="change">Changing in either direction</option></select></label>
            {!needsReading && selectedPlace && variables.some(v => v.id === spec.variable_id) && <p className="will-test" role="status"><b>This check will test:</b> {labelOf(spec.variable_id).toLowerCase()} · {spec.place.name} · {seasonName(spec.season).toLowerCase()} · {spec.start_year}–{spec.end_year} · {DIRECTION_WORD[spec.claim_direction]}</p>}
            {error && <div className="error" role="alert">{error}</div>}
            <button className="primary-button" type={needsReading ? 'button' : 'submit'} onClick={needsReading ? () => void readClaim() : undefined} disabled={!isLive || busy || reading || catalogueLoading || !variables.length}>{reading ? 'Reading the claim…' : busy ? 'Checking…' : needsReading ? 'Read claim' : 'Check claim'} <span aria-hidden="true">→</span></button>
            <p className="field-help">{isLive ? 'Your backend performs the calculations.' : 'Custom checks need the live service.'}</p>
          </form>
          </details>
        </aside>
        <section className="trend-panel" aria-labelledby="trend-heading">
          <h2 id="trend-heading">Trend map</h2>
          <LayerControls index={layerIndex} value={layerKey} layer={layer} onChange={chooseLayer} fade={fade} onFade={setFade} labelOf={labelOf} />
          {pickNote && <p className="trend-note" role="status">{pickNote}</p>}
          {view && <PairCallout view={view} variableLabel={labelOf(view.layer.variable_id)} />}
        </section>
        {result && <button type="button" className="see-evidence" onClick={() => document.getElementById('results-section')?.scrollIntoView({ behavior: 'smooth' })}>See the evidence <span aria-hidden="true">↓</span></button>}
        </div> : <div className="investigation-panel" ref={setPanelSlot} />}
      </main>
      <footer className="credits">
        <p>Data: <a href="https://power.larc.nasa.gov/" target="_blank" rel="noreferrer">NASA POWER</a> (MERRA-2 reanalysis), <a href="https://www.ncei.noaa.gov/" target="_blank" rel="noreferrer">NOAA NCEI</a> stations and <a href="https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/" target="_blank" rel="noreferrer">Climate at a Glance</a>, <a href="https://www.nccs.nasa.gov/services/data-collections/land-based-products/nex-gddp-cmip6" target="_blank" rel="noreferrer">NEX-GDDP-CMIP6</a> scenarios.</p>
        <p>Imagery: NASA Blue Marble and Black Marble via <a href="https://www.earthdata.nasa.gov/gibs" target="_blank" rel="noreferrer">GIBS</a>. Map: <a href="https://maplibre.org/" target="_blank" rel="noreferrer">MapLibre GL JS</a>.</p>
        <p>Earth Verdict · Team Overflowers. Past observations describe evidence about change. They are not a forecast.</p>
      </footer>
    </div>
    <section className="stage" aria-label={mode === 'claims' ? 'Case location' : modes.find(([id]) => id === mode)![1]}>
      <div className="stage-globe">
        <ErrorBoundary><Suspense fallback={<div className="map-loading" role="status">Loading globe…</div>}><Globe place={mode !== 'claims' ? modePlace : selectedPlace && !spec.place.place_id.startsWith('region:') ? spec.place : null} destination={destination} station={mode === 'claims' ? result?.witness?.station ?? null : null}
          trend={mode === 'claims' ? view : null} fade={fade} frame={mode === 'claims' ? frame : null}
          pickHint={mode === 'events' ? 'Click the map to move the event there' : undefined}
          onPick={!isLive || mode === 'co2' ? undefined : mode === 'events' ? point => setEventPick(pick => ({ point, key: (pick?.key ?? 0) + 1 })) : point => checkPoint(point)} /></Suspense></ErrorBoundary>
        {mode === 'claims' ? <><div className="stage-legend">
          {frame ? <YearLegend frame={frame} variableLabel={labelOf(frame.view.map.variable_id)} /> : view && <TrendLegend view={view} fade={fade} variableLabel={labelOf(view.layer.variable_id)} />}
          <div className="stage-legend-markers"><span><i className="legend-place" />Case point</span><span><i className="legend-station" />Ground station</span></div>
        </div>
        <div className="stage-title">
          {/* With a trend layer on the map, the title describes that layer. */}
          {frame ? <>
            <div className="eyebrow">{layerSeason(frame.view.map.season)} {labelOf(frame.view.map.variable_id).toLowerCase()} over Ukraine{frame.smooth ? ` · ${frame.view.map.window}-year average` : ''}</div>
            <div className="big" data-testid="timeline-headline">{describe(frame).headline}</div>
          </> : layer ? <>
            <div className="eyebrow">{layerSeason(layer.season)} · {layer.start_year}–{layer.end_year}</div>
            <div className="big">Where is {labelOf(layer.variable_id).toLowerCase()} changing over Ukraine?</div>
          </> : <>
            {result && <div className="eyebrow">{seasonName(result.case.season)} · {result.case.start_year}–{result.case.end_year}{source ? ` · ${source}` : ''}</div>}
            <div className="big">Where is {result ? result.variable.label.toLowerCase() : 'the climate'} changing?</div>
          </>}
          <div className="src">{frame ? describe(frame).detail : selectedPlace ? spec.place.name : 'Choose a place or pick a point'}</div>
          {layer && !frame && <TrendCaption layer={layer} />}
          {(layerNote || layerStatus) && <p className="trend-status" role="status">{layerNote || layerStatus}</p>}
        </div>
        {years && <Timeline view={years} index={frame ? frame.index : null} smooth={smooth} onIndex={pickYear} onSmooth={setSmooth} />}
        </> : <>
          {/* Events and CO₂ write their own headline here; the globe shows where (or, for CO₂, the whole planet). */}
          {mode === 'events' && <div className="stage-legend"><div className="stage-legend-markers"><span><i className="legend-place" />Event place</span></div></div>}
          <div className="stage-title stage-mode-title" ref={setStageSlot} />
        </>}
      </div>
    </section>
    <section id="results-section" className="result-panel" aria-label={mode === 'claims' ? 'Check result' : mode === 'events' ? 'Event evidence' : 'CO₂ estimate'} aria-busy={mode === 'claims' ? busy : undefined}>
      {mode !== 'claims' ? <div className="result-container">
        <div className="result-heading"><span className="step">02</span><p className="eyebrow">{mode === 'events' ? 'The evidence, in focus' : 'How it is calculated'}</p></div>
        <ErrorBoundary><Suspense fallback={<div className="empty-state" role="status">Loading…</div>}>
          {mode === 'events' ? <EventsWorkspace panel={panelSlot} stage={stageSlot} onPlace={showOnGlobe} pick={eventPick} /> : <Co2Calculator panel={panelSlot} stage={stageSlot} onGlobe={showPlanet} />}
        </Suspense></ErrorBoundary>
      </div> : <div className="result-container">
        <div className="result-heading"><span className="step">02</span><p className="eyebrow">The evidence, in focus</p></div>
        <div id="result-status" role="status" aria-live="polite" aria-atomic="true" className="sr-only">{phase === 'loading' ? 'Check in progress.' : phase === 'error' ? `Check unavailable. ${error}` : phase === 'success' && result ? `Result: ${result.verdict.replace('_', ' ')}.` : phase === 'edited' ? 'Parameters changed. Run a check to see the result.' : catalogueLoading ? 'Loading available variables.' : 'Ready to configure a check.'}</div>
        {result ? <ErrorBoundary key={JSON.stringify(result.case) + result.verdict}><VerdictCard result={result} saved={resultSaved} /><CaseFile result={result} /></ErrorBoundary> : <div className="empty-state"><span aria-hidden="true">◎</span><h2>{busy ? 'Checking the evidence…' : 'Ready when you are.'}</h2><p>{busy ? 'Fetching satellite records and the nearest weather station. A new place can take up to a minute.' : 'Set your parameters and select “Check claim”. Your result will appear here.'}</p></div>}
      </div>}
    </section>
  </div>;
}

createRoot(document.getElementById('root')!).render(<StrictMode><ErrorBoundary><App /></ErrorBoundary></StrictMode>);
