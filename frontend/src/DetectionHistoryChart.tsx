import { useId } from 'react';
import type { CheckResult } from './types';

type History = NonNullable<CheckResult['detection_history']>;
const width = 600;
const height = 170;
const pad = 12;

export function DetectionHistoryChart({ history, result, endYear }: { history: History; result: CheckResult; endYear: number }) {
  const id = useId();
  const lastYear = history.points.at(-1)!.end_year;
  const x = (year: number) => pad + (year - history.start_year) / Math.max(1, lastYear - history.start_year) * (width - pad * 2);
  const py = (p: number) => pad + -Math.log10(Math.max(p, 0.000001)) / 6 * (height - pad * 2);
  const current = history.points.find(point => point.end_year === endYear)!;
  const valid = result.series.flatMap(point => point.value === null ? [] : [point.value]);
  const min = valid.length ? Math.min(...valid) : 0; const max = valid.length ? Math.max(...valid) : 0;
  const oy = (value: number) => height - pad - (value - min) / (max - min || 1) * (height - pad * 2);
  let segmentOpen = false;
  const curve = history.points.map(point => {
    if (point.p === null || point.end_year > endYear) { segmentOpen = false; return ''; }
    const command = segmentOpen ? 'L' : 'M'; segmentOpen = true;
    return `${command}${x(point.end_year)},${py(point.p)}`;
  }).join(' ');
  return <div className="history-charts">
    <figure>
      <figcaption>Observed values · {result.variable.units}</figcaption>
      <div className="chart-scale"><span>{valid.length ? `${min} to ${max} ${result.variable.units}` : 'No observations supplied'}</span><span>Muted points are outside the selected period</span></div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-labelledby={`${id}-observed`}>
        <title id={`${id}-observed`}>Observed values from {history.start_year} to {lastYear}, selected through {endYear}. Missing observations have no point.</title>
        <line className="chart-axis" x1={pad} x2={width - pad} y1={height - pad} y2={height - pad} />
        {result.series.map(point => point.value === null ? null : <circle key={point.year} cx={x(point.year)} cy={oy(point.value)} r="3.5" className={point.year <= endYear ? 'observation-point' : 'muted-point'}><title>{point.year}: {point.value} {result.variable.units}</title></circle>)}
        <line className="chart-cursor" x1={x(endYear)} x2={x(endYear)} y1={pad} y2={height - pad} />
      </svg>
      <div className="chart-scale"><span>{history.start_year}</span><span>{lastYear}</span></div>
    </figure>
    <figure>
      <figcaption>Evidence as the record grows · p-value</figcaption>
      <div className="chart-scale"><span>Logarithmic scale: 1 to ≤0.000001</span><span>Dashed line: threshold {history.alpha}</span></div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-labelledby={`${id}-p`}>
        <title id={`${id}-p`}>p-values for prefixes of the observations. The dashed threshold is {history.alpha}; the selected end year is {endYear}.</title>
        <line className="chart-threshold" data-testid="p-threshold" data-value={history.alpha} x1={pad} x2={width - pad} y1={py(history.alpha)} y2={py(history.alpha)} />
        <path d={curve} className="history-curve" />
        <line className="chart-cursor" x1={x(endYear)} x2={x(endYear)} y1={pad} y2={height - pad} />
        {current.p !== null && <circle data-testid="selected-p-point" data-value={current.p} cx={x(endYear)} cy={py(current.p)} r="5" className="selected-point" />}
      </svg>
      <div className="chart-scale"><span>{history.start_year}</span><span>{lastYear}</span></div>
    </figure>
  </div>;
}
