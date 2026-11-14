import type { CheckResult } from '../types';
import { sourceIndex, type MethodKind } from '../format';
import './steps.css';

type Step = CheckResult['steps'][number];
type YearValue = { year: number; value: number | null };

const order: Step['id'][] = ['raw', 'season', 'yearly', 'trend', 'random_check', 'robustness', 'witness', 'verdict'];
const monthLetters = 'JFMAMJJASOND';
const seasonMonths: Record<string, number[]> = { year: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], DJF: [12, 1, 2], MAM: [3, 4, 5], JJA: [6, 7, 8], SON: [9, 10, 11] };
const verdictMarks = { confirmed: '✓', refuted: '×', not_proven: '?' };
const W = 96, H = 28;

// Pixel mapping only: one path per run of non-null values, so gaps stay gaps.
function sparkPath(points: YearValue[], x: (year: number) => number, y: (value: number) => number) {
  let path = '', open = false;
  for (const point of points) {
    if (point.value === null) { open = false; continue; }
    path += `${open ? 'L' : 'M'}${x(point.year).toFixed(1)},${y(point.value).toFixed(1)}`;
    open = true;
  }
  return path;
}

function Spark({ lines, label }: { lines: { points: YearValue[]; className: string }[]; label: string }) {
  const all = lines.flatMap(line => line.points);
  const values = all.flatMap(point => point.value === null ? [] : [point.value]);
  const years = all.map(point => point.year);
  const [x0, x1, y0, y1] = [Math.min(...years), Math.max(...years), Math.min(...values), Math.max(...values)];
  const x = (year: number) => 2 + (year - x0) / ((x1 - x0) || 1) * (W - 4);
  const y = (value: number) => H - 2 - (value - y0) / ((y1 - y0) || 1) * (H - 4);
  return <svg className="step-mini" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label}>
    {lines.map(line => <path key={line.className} className={line.className} d={sparkPath(line.points, x, y)} />)}
  </svg>;
}

function Mini({ id, result: r }: { id: Step['id']; result: CheckResult }) {
  if (id === 'season') {
    const months = typeof r.case.season === 'number' ? [r.case.season] : seasonMonths[r.case.season];
    return <svg className="step-mini" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Months used: ${months.join(', ')}`}>
      {[...monthLetters].map((letter, i) => <g key={i} className={months.includes(i + 1) ? 'month-on' : 'month-off'}>
        <rect x={i * 8} y={2} width={7} height={14} rx={1.5} /><text x={i * 8 + 3.5} y={25}>{letter}</text>
      </g>)}
    </svg>;
  }
  if (id === 'yearly') return <Spark label={`Sparkline of ${r.series.length} yearly values`} lines={[{ points: r.series, className: 'spark-series' }]} />;
  if (id === 'robustness' && r.robustness.length) {
    const x0 = Math.min(...r.robustness.map(w => w.start_year)), x1 = Math.max(...r.robustness.map(w => w.end_year));
    const x = (year: number) => (year - x0) / ((x1 - x0) || 1) * W;
    const row = (H - 2) / r.robustness.length;
    return <svg className="step-mini" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={r.robustness.map(w => `${w.start_year}–${w.end_year}: ${w.significant ? 'significant' : 'not significant'}`).join('; ')}>
      {r.robustness.map((w, i) => <rect key={i} className={w.significant ? 'window-on' : 'window-off'} x={x(w.start_year)} y={1 + i * row} width={x(w.end_year) - x(w.start_year)} height={row - 1.5} rx={1} />)}
    </svg>;
  }
  if (id === 'witness' && r.witness) return <Spark label={`NASA POWER and station ${r.witness.station.name} yearly values; breaks are years without a station measurement`}
    lines={[{ points: r.series, className: 'spark-series' }, { points: r.witness.series, className: 'spark-station' }]} />;
  if (id === 'verdict') return <span className={`step-verdict step-verdict-${r.verdict}`} aria-hidden="true">{verdictMarks[r.verdict]}</span>;
  return null;
}

// Steps are shown exactly as the backend wrote them; sources are chosen by step id, never by text.
export function StepPipeline({ result: r, onSource }: { result: CheckResult; onSource: (target: number | MethodKind) => void }) {
  const byId = new Map(r.steps.map(step => [step.id, step]));
  const source = (id: Step['id']): { target: number | MethodKind; label: string } | undefined => {
    if (['raw', 'season', 'yearly'].includes(id)) { const i = sourceIndex('series.0.value', r); return i === undefined ? undefined : { target: i, label: r.provenance[i].source }; }
    if (id === 'witness') { const i = r.witness ? sourceIndex('witness.series.0.value', r) : undefined; return i === undefined ? undefined : { target: i, label: r.provenance[i].source }; }
    return { target: 'statistics', label: 'Backend statistics' };
  };
  return <section className="step-pipeline" aria-labelledby="steps-heading">
    <h3 id="steps-heading">How the verdict was reached · 8 steps</h3>
    <ol>{order.map((id, i) => {
      const step = byId.get(id);
      const link = source(id);
      return <li key={id} className="pipeline-step" data-step={id}>
        <span className="step-number" aria-hidden="true">{i + 1}</span>
        {step ? <div className="step-text">
          <span className="step-head"><span className="step-title">{step.title}</span> <strong className="step-value">{step.value}</strong></span>
          <span className="step-detail">{step.detail}{link && <> <button type="button" className="text-button step-source" onClick={() => onSource(link.target)}>{link.label}</button></>}</span>
        </div> : <div className="step-text"><span className="step-title">Step not supplied by the backend</span></div>}
        <Mini id={id} result={r} />
      </li>;
    })}</ol>
    <p className="step-note">Full method comparison, every tested period and all exact values are in “How we checked this” below.</p>
  </section>;
}
