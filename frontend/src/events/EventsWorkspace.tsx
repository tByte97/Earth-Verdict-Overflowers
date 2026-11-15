import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { findPlaces, isLive } from '../api';
import { number } from '../format';
import type { Place } from '../types';
import { pointPlace, type PickedPoint } from '../globe/place';
import { eventOverlay, type Overlay } from '../globe/overlays';
import { getCompounds, getEventSites, getProfile, runEvent, savedEvent } from './api';
import { EventCard } from './EventCard';
import { EventChart, indexYm, ymIndex } from './EventChart';
import type { Compound, EventProfile, EventResult, EventSite } from './schema';
import './events.css';

type Setup = { compound_id: string; place: Place; window_years: number; use_control: boolean; event_month: string; label: string };
const verdictWord = { clear_change: 'Clear change', not_proven: 'Not proven' };
const reasonShort: Record<string, string> = {
  clear_change: 'shift stands out from fake dates', not_significant: 'within ordinary swings', placebo_also_changes: 'fake dates shift as much',
  too_short: 'too many months missing', no_placebo: 'too few fake dates',
};
const monthName = (ym: string) => new Intl.DateTimeFormat('en', { month: 'short', year: 'numeric' }).format(new Date(Number(ym.slice(0, 4)), Number(ym.slice(5, 7)) - 1, 1));

// The parts live in three places of the shell, like a climate claim does: the controls in the left panel,
// the verdict over the globe, the evidence under it. `pick` is a point the user clicked on the globe.
export function EventsWorkspace({ panel, stage, onPlace, onOverlay, pick }: {
  panel: HTMLElement | null; stage: HTMLElement | null; onPlace: (place: Place, title: string) => void; onOverlay: (overlay: Overlay | null) => void; pick: { point: PickedPoint; key: number } | null;
}) {
  const [sites, setSites] = useState<EventSite[]>([]);
  const [compounds, setCompounds] = useState<Compound[]>([]);
  const [siteId, setSiteId] = useState('');
  const [setup, setSetup] = useState<Setup | null>(null);
  const [profile, setProfile] = useState<EventProfile | null>(null);
  const [profileBusy, setProfileBusy] = useState(false);
  const [result, setResult] = useState<EventResult | null>(null);
  const [resultBusy, setResultBusy] = useState(false);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [places, setPlaces] = useState<Place[]>([]);
  const profileReq = useRef<AbortController | null>(null);
  const eventReq = useRef<AbortController | null>(null);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    const c = new AbortController();
    Promise.all([getEventSites(c.signal), getCompounds(c.signal)]).then(([s, comps]) => {
      setSites(s); setCompounds(comps.filter(x => x.local_signal));
      if (s.length) choosePreset(s[0]);
    }).catch(e => { if (!c.signal.aborted) setError(`Cannot load events: ${e.message}`); });
    return () => { c.abort(); profileReq.current?.abort(); eventReq.current?.abort(); window.clearTimeout(timer.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The globe follows the event's place.
  useEffect(() => {
    if (setup) onPlace(setup.place, setup.label);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [setup?.place.lat, setup?.place.lon]);
  // A click on the globe moves the event there (live mode only: a new place needs the satellite record).
  useEffect(() => {
    if (!pick || !isLive || !setup) return;
    const place = pointPlace(pick.point);
    setQuery(place.name); setPlaces([]); update({ place }, { immediate: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pick?.key]);

  const compound = compounds.find(c => c.id === setup?.compound_id);
  const bounds = compound?.event_bounds.find(b => b.window_years === setup?.window_years);

  // The profile depends on everything except the month: refetch only when those change.
  const profileKey = setup && isLive ? JSON.stringify([setup.compound_id, setup.place.lat, setup.place.lon, setup.window_years, setup.use_control]) : '';
  useEffect(() => {
    if (!profileKey || !setup) { setProfile(null); return; }
    profileReq.current?.abort(); const c = new AbortController(); profileReq.current = c;
    setProfileBusy(true); setProfile(null);
    getProfile({ compound_id: setup.compound_id, place: setup.place, window_years: setup.window_years, use_control: setup.use_control }, c.signal)
      .then(p => { if (!c.signal.aborted) setProfile(p); })
      .catch(e => { if (!c.signal.aborted) setError(e.message); })
      .finally(() => { if (!c.signal.aborted) setProfileBusy(false); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profileKey]);

  useEffect(() => {
    if (!isLive || query.trim().length < 2 || setup?.place.name === query) { setPlaces([]); return; }
    const c = new AbortController();
    const t = window.setTimeout(() => {
      setError('');
      findPlaces(query, c.signal)
        .then(p => { if (!c.signal.aborted) setPlaces(p); })
        .catch(e => {
          if (!c.signal.aborted) {
            setPlaces([]);
            setError(`Place search failed: ${e instanceof Error ? e.message : 'request failed'}`);
          }
        });
    }, 250);
    return () => { window.clearTimeout(t); c.abort(); };
  }, [query, setup?.place.name]);

  function choosePreset(site: EventSite) {
    window.clearTimeout(timer.current);
    setSiteId(site.id); setError(''); setQuery(site.place.name);
    const next = { compound_id: site.compound_id, place: site.place, window_years: site.window_years, use_control: true, event_month: site.event_month, label: site.label };
    setSetup(next);
    eventReq.current?.abort(); const c = new AbortController(); eventReq.current = c;
    setResultBusy(true);
    savedEvent(site.id, c.signal).then(r => { if (!c.signal.aborted) setResult(r); })
      .catch(e => { if (!c.signal.aborted) setError(e.message); })
      .finally(() => { if (!c.signal.aborted) setResultBusy(false); });
  }

  function update(next: Partial<Setup>, { immediate = false } = {}) {
    if (!setup) return;
    const merged = { ...setup, ...next };
    const comp = compounds.find(c => c.id === merged.compound_id);
    const allowedWindows = comp?.valid_windows ?? comp?.event_bounds.map(b => b.window_years);
    if (allowedWindows?.length && !allowedWindows.includes(merged.window_years)) {
      merged.window_years = allowedWindows.at(-1)!;
    }
    const b = comp?.event_bounds.find(x => x.window_years === merged.window_years);
    if (b) merged.event_month = merged.event_month < b.earliest ? b.earliest : merged.event_month > b.latest ? b.latest : merged.event_month;
    if (next.place || next.compound_id) { setSiteId(''); merged.label = `Event at ${merged.place.name}`; }
    setSetup(merged); setError('');
    if (!isLive) return;
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => fetchResult(merged), immediate ? 0 : 450);
  }

  function fetchResult(s: Setup) {
    eventReq.current?.abort(); const c = new AbortController(); eventReq.current = c;
    setResultBusy(true);
    runEvent({ compound_id: s.compound_id, place: s.place, event_month: s.event_month, event_label: s.label, window_years: s.window_years, use_control: s.use_control }, c.signal)
      .then(r => { if (!c.signal.aborted) setResult(r); })
      .catch(e => { if (!c.signal.aborted) setError(e.message); })
      .finally(() => { if (!c.signal.aborted) setResultBusy(false); });
  }

  const point = useMemo(() => profile?.points.find(p => p.event_month === setup?.event_month) ?? null, [profile, setup?.event_month]);
  const counts = useMemo(() => {
    if (!profile) return null;
    const clear = profile.points.filter(p => p.verdict === 'clear_change');
    return { clear: clear.length, total: profile.points.length };
  }, [profile]);
  const sliderMin = bounds ? ymIndex(bounds.earliest) : 0, sliderMax = bounds ? ymIndex(bounds.latest) : 0;
  const series = profile ?? result;
  const validWindows = compound?.valid_windows ?? compound?.event_bounds.map(b => b.window_years) ?? [1, 2, 3, 4, 5];
  const stale = result && setup && (result.spec.event_month !== setup.event_month || result.spec.window_years !== setup.window_years || result.spec.compound_id !== setup.compound_id || result.spec.use_control !== setup.use_control || result.spec.place.lat !== setup.place.lat || result.spec.place.lon !== setup.place.lon);

  const controls = <>
    <aside className="case-panel ev-controls" aria-labelledby="ev-heading">
      <div className="panel-heading"><span className="step">01</span><div><p className="eyebrow">Pollution events</p><h2 id="ev-heading">Did the air change?</h2></div></div>
      <p className="field-help">Pick a place and the month something happened there: a plant opened or closed, a lockdown began. We compare the satellite record before and after that month with a ring of points about 120 km around it.</p>
      <div className="cases ev-events" role="group" aria-label="Ready-made events">{sites.map(s =>
        <button key={s.id} type="button" className="case" data-event={s.id} aria-pressed={siteId === s.id} onClick={() => choosePreset(s)}>
          <b>{s.label}</b><span>{compounds.find(c => c.id === s.compound_id)?.label ?? s.compound_id} · {monthName(s.event_month)}</span>
        </button>)}</div>
      {siteId && <p className="field-help">{sites.find(s => s.id === siteId)?.note}</p>}
      {setup && <details className="case-parameters" open={isLive}><summary>{isLive ? 'Change the place, the gas or the window' : 'What was compared'}</summary>
        {isLive && <><label>Place<input value={query} autoComplete="off" onChange={e => setQuery(e.target.value)} /></label>
          {places.length > 0 && <ul className="place-results">{places.map(p => <li key={p.place_id}><button type="button" onClick={() => { setQuery(p.name); setPlaces([]); update({ place: p }, { immediate: true }); }}>{p.name}</button></li>)}</ul>}</>}
        <label>What to measure<select value={setup.compound_id} disabled={!isLive} onChange={e => update({ compound_id: e.target.value }, { immediate: true })}>
          {compounds.map(c => <option key={c.id} value={c.id}>{c.label}{c.kind === 'reanalysis' ? ' · model' : ''}</option>)}
        </select></label>
        {compound && <p className="field-help">{compound.definition}</p>}
        <fieldset><legend>Compare … years before and after</legend><div className="ev-segment" role="radiogroup">
          {validWindows.map(w => <button key={w} type="button" role="radio" aria-checked={setup.window_years === w} className={setup.window_years === w ? 'on' : ''} disabled={!isLive} onClick={() => update({ window_years: w }, { immediate: true })}>{w}</button>)}
        </div></fieldset>
        <label className="ev-toggle"><input type="checkbox" checked={setup.use_control} disabled={!isLive} onChange={e => update({ use_control: e.target.checked }, { immediate: true })} /> Subtract the surrounding ring (recommended)</label>
        {isLive && <p className="field-help">You can also click the globe to move the event to that spot.</p>}
        {!isLive && <p className="field-help">Saved mode shows the ready-made events. Connect the backend to move the date or choose your own place.</p>}
      </details>}
      {error && <div className="error" role="alert">{error}</div>}
    </aside>
    {result && <button type="button" className="see-evidence" onClick={() => document.getElementById('results-section')?.scrollIntoView({ behavior: 'smooth' })}>See the evidence <span aria-hidden="true">↓</span></button>}
  </>;

  // Over the globe: what was checked and the answer, in the words the card below uses.
  const shown = result && !stale ? result : null;
  // The globe draws the answer at the place: a haze in the answer's colour and the ring of comparison points.
  const overlay = useMemo(() => (shown ? eventOverlay(shown) : null), [shown]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { onOverlay(overlay); }, [overlay?.key]);
  const headline = setup && <>
    <div className="eyebrow">Pollution event{compound ? ` · ${compound.label}` : ''} · {monthName(setup.event_month)}</div>
    <div className="big">{setup.label}</div>
    <div className="src">{setup.place.name}</div>
    {shown ? <p className={`stage-verdict ${shown.verdict}`} data-testid="stage-verdict"><strong>{verdictWord[shown.verdict]}</strong>{shown.effect !== null && <> · {number(shown.effect, true)} {shown.compound.units} after the event</>} · {reasonShort[shown.reason]}</p>
      : (resultBusy || profileBusy) && <p className="trend-status" role="status">Checking the satellite record…</p>}
  </>;

  return <>
    {panel && createPortal(controls, panel)}
    {stage && createPortal(headline, stage)}
    <section className="ev-main" aria-label="Event evidence" aria-busy={profileBusy || resultBusy}>
      {setup && <div className="verdict-card ev-slider-card">
        <div className="ev-slider-head">
          <div><span className="eyebrow">Event month</span><strong className="ev-month">{monthName(setup.event_month)}</strong></div>
          {point ? <div className={`ev-readout ${point.verdict}`}><strong>{verdictWord[point.verdict]}</strong><span>{point.effect === null ? reasonShort[point.reason] : `${number(point.effect, true)} ${compound?.units ?? ''} · ${reasonShort[point.reason]}`}</span></div>
            : profileBusy ? <div className="ev-readout"><span>Downloading the satellite record for this place… The first time can take a minute or two.</span></div> : null}
        </div>
        {bounds && <input className="ev-range" type="range" min={sliderMin} max={sliderMax} step={1} value={ymIndex(setup.event_month)} disabled={!isLive || profileBusy}
          aria-label="Event month" aria-valuetext={monthName(setup.event_month)}
          onChange={e => update({ event_month: indexYm(Number(e.target.value)) })} />}
        {bounds && <div className="ev-range-ends"><span>{monthName(bounds.earliest)}</span><span>{monthName(bounds.latest)}</span></div>}
        {series && compound && <EventChart site={series.site} control={setup.use_control ? series.control : null} units={compound.units}
          eventMonth={setup.event_month} windowYears={setup.window_years} profile={profile?.points ?? null} onPick={m => update({ event_month: m })} />}
        <div className="ev-legend">
          <span><i className="ev-key-site" />At the place</span>{setup.use_control && <span><i className="ev-key-control" />Surrounding ring</span>}
          {profile && <><span><i style={{ background: 'var(--ev-clear)' }} />Clear change</span><span><i style={{ background: 'var(--ev-trend)' }} />Fake dates shift as much</span><span><i style={{ background: 'var(--ev-noise)' }} />Within noise</span><span><i style={{ background: 'var(--ev-missing)' }} />Not enough data</span></>}
        </div>
        {counts && <p className="help-text">A clear change would be reported for {counts.clear} of the {counts.total} possible months here. Drag along the bottom strip or move the slider to see how the answer depends on the date you choose.</p>}
      </div>}
      {result ? <div className={stale || resultBusy ? 'ev-stale' : ''}><EventCard result={result} saved={!isLive || (!!siteId && result.spec.event_month === sites.find(s => s.id === siteId)?.event_month)} /></div>
        : <div className="empty-state"><span aria-hidden="true">◎</span><h2>{resultBusy ? 'Checking the evidence…' : 'Choose an event.'}</h2></div>}
    </section>
  </>;
}
