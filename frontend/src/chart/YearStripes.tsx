import type { CheckResult } from '../types';
import { number, period } from '../format';
import './chart.css';

// Low/high ends of the ramp per variable; the middle is a neutral grey.
const ramps: Record<string, [string, string, string, string]> = {
  air_temp: ['#3b6fd1', '#d6452f', 'cooler', 'warmer'],
  global_temp: ['#3b6fd1', '#d6452f', 'cooler', 'warmer'],
  precip: ['#c99a3b', '#2f8f8a', 'drier', 'wetter'],
  snow_depth: ['#a8743f', '#4a8fd6', 'less snow', 'more snow'],
};
const neutral = [236, 236, 236];
const rgb = (hex: string) => [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));

function stripeColor(t: number, low: string, high: string) {
  const end = rgb(t < 0 ? low : high);
  return `rgb(${neutral.map((c, i) => Math.round(c + (end[i] - c) * Math.min(1, Math.abs(t)))).join(',')})`;
}


// Colour is value − baseline.mean from the backend, on a diverging scale with zero in the middle.
export function YearStripes({ result: r }: { result: CheckResult }) {
  const [low, high, lowLabel, highLabel] = ramps[r.variable.id] ?? ['#7a8fa6', '#b5643c', 'lower', 'higher'];
  const units = r.variable.units;
  const { mean, period: basePeriod, kind, n_years } = r.baseline;
  const baselineText = kind === 'normal_1991_2020'
    ? `the ${basePeriod} normal: ${number(mean)} ${units}, the average of ${n_years} years`
    : `the average of the whole record, ${basePeriod}: ${number(mean)} ${units} over ${n_years} years. The record does not cover enough of 1991–2020 for a normal`;
  const values = r.series.flatMap(point => point.value === null ? [] : [point.value]);
  const scale = Math.max(...values.map(value => Math.abs(value - mean))) || 1;
  const first = r.series[0]?.year, last = r.series.at(-1)?.year;
  return <figure className="year-stripes">
    <figcaption>Each stripe is one year · {r.variable.label}, {period(r)}</figcaption>
    <div className="stripes" role="img" aria-label={`${r.series.length} yearly stripes from ${first} to ${last}. Colour shows how ${lowLabel} or ${highLabel} each year was than the ${basePeriod} average. Exact values are in the table below the chart.`}>
      {r.series.map(point => <div key={point.year} className={point.value === null ? 'stripe-missing' : undefined}
        style={point.value === null ? undefined : { background: stripeColor((point.value - mean) / scale, low, high) }}
        title={`${point.year}: ${point.value === null ? 'no data' : `${number(point.value)} ${units}`} · ${basePeriod} average: ${number(mean)} ${units}`} />)}
    </div>
    <div className="stripe-axis" aria-hidden="true"><span>{first}</span><span>{last}</span></div>
    <p className="stripe-legend">
      <span>{lowLabel}</span>
      <span className="ramp" aria-hidden="true" style={{ background: `linear-gradient(90deg,${low},rgb(${neutral}),${high})` }} />
      <span>{highLabel}</span>
      <span className="stripe-note">Colour is relative to {baselineText}. Grey means close to that average. Hover a stripe to see its year.</span>
    </p>
  </figure>;
}
