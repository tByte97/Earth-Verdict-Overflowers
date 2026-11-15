import type { CheckResult } from '../types';
import { fieldContext, number, seriesSourceName, sourceIndex, type MethodKind } from '../format';
import './steps.css';

type Step = CheckResult['steps'][number];
type Point = { x: number; value: number | null };

const order: Step['id'][] = ['raw', 'season', 'yearly', 'trend', 'random_check', 'robustness', 'witness', 'verdict'];
const monthLetters = 'JFMAMJJASOND';
const verdictMarks = { confirmed: '✓', refuted: '×', not_proven: '?' };
const methodsReason = { direction_differs: 'the methods disagree on the direction', significance_differs: 'the methods disagree on whether it stands out from chance' };
const W = 96, H = 28;

const yearPoints = (series: { year: number; value: number | null }[]): Point[] => series.map(p => ({ x: p.year, value: p.value }));
const monthPoints = (monthly: { month: string; value: number | null }[]): Point[] =>
  monthly.map(m => ({ x: Number(m.month.slice(0, 4)) * 12 + Number(m.month.slice(5, 7)) - 1, value: m.value }));

// Pixel mapping only: one path per run of non-null values, so gaps stay gaps.
function sparkPath(points: Point[], x: (v: number) => number, y: (v: number) => number) {
  let path = '', open = false;
  for (const point of points) {
    if (point.value === null) { open = false; continue; }
    path += `${open ? 'L' : 'M'}${x(point.x).toFixed(1)},${y(point.value).toFixed(1)}`;
    open = true;
  }
  return path;
}

function scales(xs: number[], ys: number[]) {
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  return {
    x: (v: number) => 2 + (v - x0) / ((x1 - x0) || 1) * (W - 4),
    y: (v: number) => H - 2 - (v - y0) / ((y1 - y0) || 1) * (H - 4),
  };
}

function Spark({ lines, label }: { lines: { points: Point[]; className: string }[]; label: string }) {
  const all = lines.flatMap(line => line.points);
  const values = all.flatMap(point => point.value === null ? [] : [point.value]);
  if (!values.length) return null;
  const { x, y } = scales(all.map(p => p.x), values);
  return <svg className="step-mini" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label}>
    {lines.map(line => <path key={line.className} className={line.className} d={sparkPath(line.points, x, y)} />)}
  </svg>;
}

// Yearly values with the backend's Sen-slope fan (sen.band): the browser draws, it does not fit.
function TrendMini({ r }: { r: CheckResult }) {
  const band = r.sen.band;
  const values = [...r.series.flatMap(p => p.value === null ? [] : [p.value]), ...band.flatMap(b => [b.low, b.high])];
  if (!band.length || !values.length) return null;
  const { x, y } = scales([...r.series.map(p => p.year), ...band.map(b => b.year)], values);
  const area = [...band.map(b => `${x(b.year).toFixed(1)},${y(b.high).toFixed(1)}`), ...[...band].reverse().map(b => `${x(b.year).toFixed(1)},${y(b.low).toFixed(1)}`)].join(' ');
  return <svg className="step-mini" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Yearly values with the trend line and its 95% range, ${band[0].year}–${band.at(-1)!.year}`}>
    <polygon className="trend-band" points={area} />
    <path className="spark-series spark-faint" d={sparkPath(yearPoints(r.series), x, y)} />
    <path className="trend-mid" d={sparkPath(band.map(b => ({ x: b.year, value: b.mid })), x, y)} />
  </svg>;
}

function Mini({ step, result: r }: { step: Step | undefined; result: CheckResult }) {
  const id = step?.id;
  if (id === 'raw' && step?.monthly?.length) return <Spark label={`Sparkline of ${step.n_months ?? step.monthly.length} monthly values`} lines={[{ points: monthPoints(step.monthly), className: 'spark-series' }]} />;
  if (id === 'season' && step?.months) {
    const months = step.months;
    return <svg className="step-mini" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Months used: ${months.join(', ')}`}>
      {[...monthLetters].map((letter, i) => <g key={i} className={months.includes(i + 1) ? 'month-on' : 'month-off'}>
        <rect x={i * 8} y={2} width={7} height={14} rx={1.5} /><text x={i * 8 + 3.5} y={25}>{letter}</text>
      </g>)}
    </svg>;
  }
  if (id === 'yearly') return <Spark label={`Sparkline of ${r.series.length} yearly values`} lines={[{ points: yearPoints(r.series), className: 'spark-series' }]} />;
  if (id === 'trend') return <TrendMini r={r} />;
  if (id === 'robustness' && r.robustness.length) {
    const x0 = Math.min(...r.robustness.map(w => w.start_year)), x1 = Math.max(...r.robustness.map(w => w.end_year));
    const x = (year: number) => (year - x0) / ((x1 - x0) || 1) * W;
    const row = (H - 2) / r.robustness.length;
    return <svg className="step-mini" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={r.robustness.map(w => `${w.start_year}–${w.end_year}: ${w.significant ? 'significant' : 'not significant'}`).join('; ')}>
      {r.robustness.map((w, i) => <rect key={i} className={w.significant ? 'window-on' : 'window-off'} x={x(w.start_year)} y={1 + i * row} width={x(w.end_year) - x(w.start_year)} height={row - 1.5} rx={1} />)}
    </svg>;
  }
  if (id === 'witness' && r.witness) return <Spark label={`${seriesSourceName(r)} and station ${r.witness.station.name} yearly values; breaks are years without a station measurement`}
    lines={[{ points: yearPoints(r.series), className: 'spark-series' }, { points: yearPoints(r.witness.series), className: 'spark-station' }]} />;
  if (id === 'verdict') return <span className={`step-verdict step-verdict-${r.verdict}`} aria-hidden="true">{verdictMarks[r.verdict]}</span>;
  return null;
}

// Resolves a backend dot path ("mk.p", "witness.sen.slope_per_decade") in the result.
function resolve(r: CheckResult, path: string): unknown {
  return path.split('.').reduce<unknown>((node, key) => (node && typeof node === 'object' ? (node as Record<string, unknown>)[key] : undefined), r);
}

function FieldValue({ r, path }: { r: CheckResult; path: string }) {
  const value = resolve(r, path);
  let shown: string;
  if (typeof value === 'number') {
    const unit = fieldContext(path, r).unit;
    shown = unit === 'calendar year' ? String(value) : `${number(value)}${unit.startsWith('Not supplied') || unit === 'dimensionless' ? '' : ` ${unit}`}`;
  }
  else if (Array.isArray(value)) shown = `${value.length} values`;
  else if (value === null || value === undefined) shown = 'not supplied';
  else shown = String(value);
  return <div><dt><code>{path}</code></dt><dd>{shown}</dd></div>;
}

function Extra({ step }: { step: Step }) {
  if (step.id === 'season' && step.years_dropped?.length) return <span className="step-extra">Left out because a month is missing: {step.years_dropped.join(', ')}.</span>;
  if (step.id === 'random_check' && step.alpha !== null) {
    const methods = step.methods_agree === null ? '' : step.methods_agree ? ' · Sen/Mann–Kendall and least squares agree.' : ` · Caution: ${step.methods_reason ? methodsReason[step.methods_reason] : 'the methods disagree'}.`;
    return <span className={`step-extra ${step.methods_agree === false ? 'step-warn' : ''}`}>Threshold: p below {step.alpha}{methods}</span>;
  }
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
          <Extra step={step} />
          {step.fields.length > 0 && <dl className="step-fields" aria-label="Exact values this step summarises">{step.fields.map(path => <FieldValue key={path} r={r} path={path} />)}</dl>}
        </div> : <div className="step-text"><span className="step-title">Step not supplied by the backend</span></div>}
        <Mini step={step} result={r} />
      </li>;
    })}</ol>
    <p className="step-note">Full method comparison, every tested period and all exact values are in “How we checked this” below.</p>
  </section>;
}
