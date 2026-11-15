import { useEffect, useId, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';
import type { CheckResult } from '../types';
import { number, period, safeUrl, sourceIndex } from '../format';
import { niceStep, palette, seasonName, trendColor } from './ramp';
import './chart.css';

const H = 210;
const STRIPE = 14;
const P = { l: 44, r: 12, t: 14, b: 24 };
const STATION = '#a99be6';
const axisNumber = (x: number) => Math.abs(x) >= 10 ? x.toFixed(0) : Math.abs(x) >= 1 ? x.toFixed(1) : Math.abs(x) >= 0.1 ? x.toFixed(2) : x.toFixed(3);

// One "M…L…" path per run of supplied values: a null year breaks the line, it is never bridged or drawn as zero.
function gappedPath(points: { year: number; value: number | null }[], x: (year: number) => number, y: (value: number) => number) {
  let d = '', open = false;
  for (const point of points) {
    if (point.value === null) { open = false; continue; }
    d += `${open ? 'L' : 'M'}${x(point.year).toFixed(1)},${y(point.value).toFixed(1)}`;
    open = true;
  }
  return d;
}

function SourceLink({ result: r, path, children }: { result: CheckResult; path: string; children: string }) {
  const index = sourceIndex(path, r);
  const url = index === undefined ? undefined : safeUrl(r.provenance[index].url);
  return url ? <a href={url} target="_blank" rel="noreferrer">{children} <span aria-hidden="true">↗</span></a> : <>{children}</>;
}

// Draws only supplied values: series, sen.band (mid/low/high), witness.series, baseline.mean and, when present,
// detection_history.emerged_year. Colour scales are display choices; nothing is fitted or averaged here.
export function RecordChart({ result: r }: { result: CheckResult }) {
  const id = useId();
  const box = useRef<HTMLDivElement>(null);
  const [W, setW] = useState(560);
  const [hover, setHover] = useState<number | null>(null);
  useEffect(() => {
    const node = box.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => setW(Math.max(280, Math.round(entry.contentRect.width))));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const units = r.variable.units;
  const { pal, down, up } = palette(r.variable.id);
  const trend = trendColor(r);
  const witness = r.witness;
  const station = new Map(witness?.series.map(point => [point.year, point.value]) ?? []);
  const band = new Map(r.sen.band.map(point => [point.year, point]));
  const series = r.series;
  const first = series[0]?.year ?? r.case.start_year, last = series.at(-1)?.year ?? r.case.end_year;
  const { mean, period: basePeriod, kind } = r.baseline;
  const emerged = r.detection_history?.emerged_year ?? null;
  const season = seasonName(r.case.season);

  const shown = [
    ...series.map(point => point.value), ...(witness?.series.map(point => point.value) ?? []),
    ...r.sen.band.flatMap(point => [point.low, point.high]), mean,
  ].filter((value): value is number => value !== null);
  let lo = Math.min(...shown), hi = Math.max(...shown);
  const pad = (hi - lo) * 0.12 || 1; lo -= pad; hi += pad;
  const x = (year: number) => P.l + (year - first) / Math.max(1, last - first) * (W - P.l - P.r);
  const y = (value: number) => P.t + (1 - (value - lo) / (hi - lo)) * (H - P.t - P.b);
  const step = niceStep((hi - lo) / 4);
  const ticks: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) ticks.push(v);
  const decades: number[] = [];
  for (let year = Math.ceil(first / 10) * 10; year <= last; year += 10) decades.push(year);
  // Stripe colour: distance from baseline.mean on a symmetric display scale set by the largest distance.
  const spread = Math.max(...series.flatMap(point => point.value === null ? [] : [Math.abs(point.value - mean)])) || 1;
  const cell = (W - P.l - P.r) / Math.max(1, last - first);
  const bandPolygon = [...r.sen.band.map(point => `${x(point.year)},${y(point.high)}`), ...[...r.sen.band].reverse().map(point => `${x(point.year)},${y(point.low)}`)].join(' ');

  const yearAt = (clientX: number, svg: SVGSVGElement) => {
    const rect = svg.getBoundingClientRect();
    const year = Math.round(first + (clientX - rect.left - P.l) / (W - P.l - P.r) * (last - first));
    return year >= first && year <= last ? year : null;
  };
  const onPointer = (event: PointerEvent<SVGSVGElement>) => setHover(yearAt(event.clientX, event.currentTarget));
  const onKey = (event: KeyboardEvent<SVGSVGElement>) => {
    const move = { ArrowLeft: -1, ArrowRight: 1 }[event.key];
    if (move === undefined) return;
    event.preventDefault();
    setHover(year => Math.min(last, Math.max(first, (year ?? (move > 0 ? first - 1 : last + 1)) + move)));
  };

  const value = hover === null ? undefined : series.find(point => point.year === hover)?.value;
  const mid = hover === null ? undefined : band.get(hover)?.mid;
  const measured = hover === null ? undefined : station.get(hover);
  const tipLeft = hover !== null && x(hover) > W / 2;

  return <section className="record" aria-labelledby={`${id}-title`} data-testid="record-chart">
    <h3 id={`${id}-title`}>The record at this spot</h3>
    <p className="record-context">{r.case.place.name} · {season} {r.variable.label.toLowerCase()} · {period(r)} · absolute values in {units}</p>
    <div className="record-plot" ref={box}>
      <svg viewBox={`0 0 ${W} ${H + STRIPE + 6}`} width={W} height={H + STRIPE + 6} role="img" tabIndex={0}
        aria-labelledby={`${id}-desc`} onPointerMove={onPointer} onPointerLeave={() => setHover(null)} onKeyDown={onKey} onBlur={() => setHover(null)}>
        <desc id={`${id}-desc`}>{season} {r.variable.label} at {r.case.place.name}, {first}–{last}, with Sen’s trend line, its 95% range{witness ? ', the ground station' : ''} and the {basePeriod} average. Use the left and right arrow keys to read single years; exact values are in the table below.</desc>
        <g className="grid">{ticks.map(v => <g key={v}><line x1={P.l} x2={W - P.r} y1={y(v)} y2={y(v)} /><text x={P.l - 6} y={y(v) + 3} textAnchor="end">{axisNumber(v)}</text></g>)}</g>
        <g className="grid">{decades.map(year => <text key={year} x={x(year)} y={H - 6} textAnchor="middle">{year}</text>)}</g>
        <polygon className="band" points={bandPolygon} fill={trend} />
        <line className="baseline" data-testid="baseline" data-value={mean} x1={P.l} x2={W - P.r} y1={y(mean)} y2={y(mean)} />
        <text className="baseline-label" x={W - P.r} y={y(mean) - 4} textAnchor="end">{basePeriod} average</text>
        {emerged !== null && <g className="emerged" data-testid="emerged-marker">
          <line x1={x(emerged)} x2={x(emerged)} y1={P.t} y2={H - P.b} />
          <text x={x(emerged) + 4} y={P.t + 9}>emerged {emerged}</text>
        </g>}
        <path className="series-line" data-testid="series-line" d={gappedPath(series, x, y)} />
        {witness && <path className="station-line" data-testid="station-line" d={gappedPath(witness.series, x, y)} stroke={STATION} />}
        {witness?.series.map(point => point.value === null ? null : <circle key={point.year} className="station-dot" cx={x(point.year)} cy={y(point.value)} r="2" fill={STATION} />)}
        {series.map(point => point.value === null ? null : <circle key={point.year} className="series-dot" data-year={point.year} cx={x(point.year)} cy={y(point.value)} r="2.6" />)}
        <path className="trend-line" data-testid="trend-line" d={gappedPath(r.sen.band.map(point => ({ year: point.year, value: point.mid })), x, y)} stroke={trend} />
        {hover !== null && <line className="crosshair" x1={x(hover)} x2={x(hover)} y1={P.t} y2={H - P.b} />}
        <g data-testid="year-stripes">{series.map(point => point.value === null ? null : <rect key={point.year} className="stripe" data-year={point.year} data-value={point.value}
          x={x(point.year) - cell / 2} y={H + 4} width={cell + 0.5} height={STRIPE} fill={pal(0.5 + (point.value - mean) / spread / 2)} />)}</g>
      </svg>
      {hover !== null && <div className="record-tip" role="status" data-testid="chart-tooltip" style={tipLeft ? { right: W - x(hover) + 10 } : { left: x(hover) + 10 }}>
        <strong>{season} {hover}</strong>
        <span>Value <b>{value == null ? 'no data' : `${number(value)} ${units}`}</b></span>
        {mid !== undefined && <span>Trend line <b>{number(mid)} {units}</b></span>}
        {witness && <span>Station <b>{measured == null ? 'no measurement' : `${number(measured)} ${units}`}</b></span>}
      </div>}
    </div>
    <ul className="record-legend">
      <li><i className="key-series" aria-hidden="true" />{season} average, {units}</li>
      <li><i className="key-trend" style={{ background: trend }} aria-hidden="true" />Sen’s trend ({number(r.sen.slope_per_decade, true)} {units} / decade)</li>
      <li><i className="key-band" style={{ background: trend }} aria-hidden="true" />95% range ({number(r.sen.ci_low, true)} to {number(r.sen.ci_high, true)} {units} / decade)</li>
      <li>{witness ? <><i className="key-station" style={{ background: STATION }} aria-hidden="true" />station {witness.station.name}, {number(witness.station.distance_km)} km away</> : 'No ground station for this place'}</li>
      <li><i className="key-baseline" aria-hidden="true" />{basePeriod} average, {number(mean)} {units}</li>
    </ul>
    <p className="record-note">
      {witness ? 'Breaks in a line are years without a measurement; they are not zero. ' : ''}
      Stripes: one per year, {down} to {up} than the {kind === 'normal_1991_2020' ? `${basePeriod} normal` : `whole-record average (${basePeriod}; the record does not cover enough of 1991–2020 for a normal)`}.
      {emerged === null ? '' : ` The dashed vertical line marks ${emerged}, when the signal left the noise.`}
    </p>
    <details className="chart-values">
      <summary>Exact values for every year <span>Received precision · missing values stay missing</span></summary>
      <div className="table-scroll chart-table"><table>
        <thead><tr><th>Year</th><th><SourceLink result={r} path="series.0.value">NASA POWER</SourceLink> · {units}</th><th>Trend line · {units}</th><th>95% range, low to high · {units}</th><th>{witness ? <><SourceLink result={r} path="witness.series.0.value">{`Station ${witness.station.name}`}</SourceLink> · {units}</> : 'Station'}</th></tr></thead>
        <tbody>{series.map(point => {
          const stationValue = station.get(point.year);
          const line = band.get(point.year);
          return <tr key={point.year}><th>{point.year}</th><td>{point.value === null ? 'no data' : String(point.value)}</td><td>{line ? String(line.mid) : 'not supplied'}</td><td>{line ? `${line.low} to ${line.high}` : 'not supplied'}</td><td>{!witness ? 'no station for this place' : stationValue == null ? 'no station measurement' : String(stationValue)}</td></tr>;
        })}</tbody>
      </table></div>
    </details>
  </section>;
}
