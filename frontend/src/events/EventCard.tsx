import { useId } from 'react';
import { number, provenanceLink } from '../format';
import type { EventResult } from './schema';
import { Explain } from './Explain';

const reasons: Record<EventResult['reason'], string> = {
  clear_change: 'A clear shift at this date compared with the surroundings, and no fake date in other years shows one as large.',
  not_significant: 'The difference before and after is not larger than ordinary month-to-month swings.',
  placebo_also_changes: 'There is a shift, but fake event dates in other years show shifts at least as large, so a broader trend or ordinary year-to-year swings can explain it.',
  no_placebo: 'Fewer than 3 fake event dates fit in the record, so an ongoing trend cannot be ruled out.',
  too_short: 'Too many months are missing (clouds, snow or polar night) in the before or after window.',
};

export function EventCard({ result: r, saved }: { result: EventResult; saved: boolean }) {
  const id = useId();
  const clear = r.verdict === 'clear_change';
  const u = r.compound.units;
  const maxAbs = Math.max(Math.abs(r.effect ?? 0), ...r.placebo.map(p => Math.abs(p.effect))) || 1;
  return <article className="verdict-card ev-card" aria-labelledby={id}>
    <div className="card-top"><span className="eyebrow">Before vs after · Verdict</span><span className="tag">{saved ? 'Saved backend response' : 'Backend response'}</span></div>
    <h2 id={id} className="claim">{r.spec.event_label}</h2>
    <p className="context">{r.spec.place.name} <span>·</span> {r.compound.label} <span>·</span> event {r.spec.event_month} <span>·</span> {r.spec.window_years}-year windows</p>
    <section className={`verdict ${clear ? 'verdict-confirmed' : 'verdict-not_proven'}`} aria-label="Verdict">
      <span className="verdict-symbol" aria-hidden="true">{clear ? '✓' : '?'}</span>
      <div><h3>{clear ? 'Clear change' : 'Not proven'}</h3><p>{reasons[r.reason]}</p></div>
    </section>
    <p className="caution">{clear
      ? <><strong>A change at that time is not proof of its cause.</strong> The satellite sees the air changing; it cannot tell whether the plant, the weather or the economy did it.</>
      : <><strong>Not proven does not mean nothing happened.</strong> The data here cannot separate this date from ordinary variation.</>}</p>
    {r.effect !== null && <div className="headline-metric">
      <span className="eyebrow">Change after the event · vs surroundings</span>
      <div className="metric-value">{number(r.effect, true)} <span>{u}</span></div>
      <p>{r.relative_change !== null ? `${number(r.relative_change * 100, true)}% of the level before · ` : ''}95% interval {number(r.ci_low, true)} to {number(r.ci_high, true)} · p = {number(r.p)}</p>
    </div>}
    {r.placebo.length > 0 && r.effect !== null && <div className="ev-placebo">
      <h4>Fake dates check <span>{r.placebo_larger} of {r.placebo.length} fake dates show a shift as large</span></h4>
      <ul>
        <li className="real"><span>{r.spec.event_month}</span><i style={{ width: `${(Math.abs(r.effect) / maxAbs) * 100}%` }} /><b>{number(r.effect, true)}</b></li>
        {r.placebo.map(p => <li key={p.event_month} className={Math.abs(p.effect) >= Math.abs(r.effect!) ? 'match' : ''}><span>{p.event_month}</span><i style={{ width: `${(Math.abs(p.effect) / maxAbs) * 100}%` }} /><b>{number(p.effect, true)}</b></li>)}
      </ul>
      <p className="help-text">The same test run at the same calendar month in other years, where nothing special happened. If those dates show shifts as large, the real date is not special.</p>
    </div>}
    {r.compound.caveat && <p className="data-note">{r.compound.caveat}</p>}
    <details className="technical">
      <summary>How we checked this <span>Steps, windows & sources</span></summary>
      <div className="detail-body">
        <ol className="ev-steps">{r.steps.map(s => <li key={s.id}><strong>{s.title}</strong> <span className="ev-step-value">{s.value}</span><p>{s.detail}</p></li>)}</ol>
        <dl className="statistics">
          <div><dt>Before window</dt><dd>{r.before.start} – {r.before.end} · {r.before.n} months with data · mean {number(r.before.mean)} {u}</dd></div>
          <div><dt>After window</dt><dd>{r.after.start} – {r.after.end} · {r.after.n} months with data · mean {number(r.after.mean)} {u}</dd></div>
          <div><dt>Block bootstrap 95% interval</dt><dd>{r.bootstrap_ci_low === null ? 'Not computed' : `${number(r.bootstrap_ci_low, true)} to ${number(r.bootstrap_ci_high, true)} ${u}`}</dd></div>
        </dl>
        {r.provenance.map((s, i) => {
          const link = provenanceLink(s.url);
          return <section className="source-record" key={i}><h4>{s.what}</h4><p><strong>{s.source}</strong> · {s.product} · retrieved {s.retrieved_at}</p>{link && <a href={link.href} target="_blank" rel="noreferrer">{link.label} <span aria-hidden="true">↗</span></a>}</section>;
        })}
      </div>
    </details>
    <Explain kind="event" result={r} />
  </article>;
}
