import { useId } from 'react';
import type { CheckResult } from './types';
import { trendColor } from './chart/ramp';
import './chart/chart.css';

type History = NonNullable<CheckResult['detection_history']>;
const width = 600;
const height = 14;

// One block per end year: filled when the backend test on the record up to that year is significant (p < alpha).
export function DetectionHistoryChart({ history, result, endYear }: { history: History; result: CheckResult; endYear: number }) {
  const id = useId();
  const points = history.points;
  const cw = (width - 2) / points.length;
  const fill = trendColor(result);
  const emerged = history.emerged_year;
  const direction = result.sen.slope_per_decade > 0 ? 'rise' : 'fall';
  return <figure className="history-timeline">
    <h5>When did the signal leave the noise?</h5>
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" style={{ height }} role="img" aria-labelledby={`${id}-title`}>
      <title id={`${id}-title`}>For each end year from {history.start_year} to {points.at(-1)!.end_year}, whether the trend in the record up to that year is significant at p &lt; {history.alpha}. Selected end year: {endYear}.</title>
      {points.map((point, i) => {
        const significant = point.status === 'ok' && point.p !== null && point.p < history.alpha;
        const selected = point.end_year === endYear;
        return <rect key={point.end_year} x={1 + i * cw} y="1" width={Math.max(1, cw - 2)} height="12" rx="2" vectorEffect="non-scaling-stroke"
          fill={significant ? fill : '#dce5dc'} className={selected ? 'block-selected' : point.end_year > endYear ? 'block-later' : undefined}
          data-year={point.end_year} data-significant={significant}
          {...(selected && point.p !== null ? { 'data-testid': 'selected-p-point', 'data-value': point.p } : {})}>
          <title>Record ending {point.end_year}: {point.p === null ? `not tested, fewer than ${history.min_observations} observed years` : `p = ${point.p}`}</title>
        </rect>;
      })}
    </svg>
    <div className="chart-scale"><span>{history.start_year}</span><span>{points.at(-1)!.end_year}</span></div>
    <p><span className="timeline-key" data-testid="p-threshold" data-value={history.alpha}>Filled block: p &lt; {history.alpha} for the record up to that year.</span> Signal emerged: <strong data-testid="emerged-year">{emerged ?? '—'}</strong></p>
    {emerged !== undefined && <p>{emerged === null
      ? 'Each block is the same test run on the record up to that year. The signal has not yet clearly left the noise.'
      : `Each block is the same test run on the record up to that year. From ${emerged} on the ${direction} stays significant: that’s when the signal left the noise.`}</p>}
  </figure>;
}
