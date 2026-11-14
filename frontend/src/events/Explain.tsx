import { useEffect, useRef, useState } from 'react';
import { isLive } from '../api';
import { explain } from './api';
import type { ChatResponse } from './schema';

const suggestions: Record<'check' | 'event' | 'co2', string[]> = {
  check: ['What does this verdict mean?', 'Why should I trust this?'],
  event: ['Does this prove the plant caused it?', 'What are the fake dates?'],
  co2: ['Why is the warming so small?', 'Where does the 44% come from?'],
};

export function Explain({ kind, result }: { kind: 'check' | 'event' | 'co2'; result: unknown }) {
  const [lang, setLang] = useState<'en' | 'uk'>('en');
  const [question, setQuestion] = useState('');
  const [answers, setAnswers] = useState<{ q: string | null; a: ChatResponse }[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const ctrl = useRef<AbortController | null>(null);
  useEffect(() => { ctrl.current?.abort(); setAnswers([]); setError(''); setBusy(false); }, [result]);
  useEffect(() => () => ctrl.current?.abort(), []);
  if (!isLive) return null;

  async function ask(q: string | null) {
    ctrl.current?.abort(); const c = new AbortController(); ctrl.current = c;
    setBusy(true); setError('');
    try { const a = await explain(kind, result, q, lang, c.signal); if (!c.signal.aborted) { setAnswers(list => [...list, { q, a }]); setQuestion(''); } }
    catch (e) { if (!c.signal.aborted) setError(e instanceof Error ? e.message : 'The explanation failed.'); }
    finally { if (!c.signal.aborted) setBusy(false); }
  }

  return <section className="explain" aria-label="Plain-language explanation">
    <div className="explain-head">
      <div><span className="eyebrow">In plain words</span><p>Gemini rewords the result above. Every number it writes is checked against the result.</p></div>
      <label className="explain-lang">Language<select value={lang} onChange={e => setLang(e.target.value as 'en' | 'uk')}><option value="en">English</option><option value="uk">Українська</option></select></label>
    </div>
    {answers.map((item, i) => <div className="explain-answer" key={i}>
      {item.q && <p className="explain-q">{item.q}</p>}
      <p>{item.a.text}</p>
      <span className={`explain-badge ${item.a.grounded ? '' : 'fallback'}`}>{item.a.grounded ? `Numbers checked · ${item.a.model}` : item.a.model.includes('busy') ? 'Built-in summary: Gemini is busy, try again in a minute' : 'Built-in summary: the model used a number that is not in the result'}</span>
    </div>)}
    {error && <div className="error" role="alert">{error}</div>}
    <div className="explain-actions">
      {!answers.length && <button type="button" className="primary-button" disabled={busy} onClick={() => ask(null)}>{busy ? 'Explaining…' : 'Explain this result'}</button>}
      {answers.length > 0 && suggestions[kind].map(s => <button key={s} type="button" className="chip" disabled={busy} onClick={() => ask(s)}>{s}</button>)}
    </div>
    {answers.length > 0 && <form className="explain-form" onSubmit={e => { e.preventDefault(); if (question.trim()) ask(question.trim()); }}>
      <input value={question} maxLength={300} placeholder="Ask about this result…" aria-label="Your question" onChange={e => setQuestion(e.target.value)} />
      <button type="submit" className="primary-button" disabled={busy || !question.trim()}>{busy ? '…' : 'Ask'}</button>
    </form>}
  </section>;
}
