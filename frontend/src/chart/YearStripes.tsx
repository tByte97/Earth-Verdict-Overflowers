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

// Colour is a display scale over the lowest–highest value of this record, not an anomaly.
export function YearStripes({ result: r }: { result: CheckResult }) {
  const [low, high, lowLabel, highLabel] = ramps[r.variable.id] ?? ['#7a8fa6', '#b5643c', 'lower', 'higher'];
  const units = r.variable.units;
  const values = r.series.flatMap(point => point.value === null ? [] : [point.value]);
  const min = Math.min(...values), max = Math.max(...values);
  const mid = (min + max) / 2, half = (max - min) / 2 || 1;
  const first = r.series[0]?.year, last = r.series.at(-1)?.year;
  return <figure className="year-stripes">
    <figcaption>Each stripe is one year · {r.variable.label}, {period(r)}</figcaption>
    <div className="stripes" role="img" aria-label={`${r.series.length} yearly stripes from ${first} to ${last}. Colour shows how ${lowLabel} or ${highLabel} each year was within this record. Exact values are in the table below the chart.`}>
      {r.series.map(point => <div key={point.year} className={point.value === null ? 'stripe-missing' : undefined}
        style={point.value === null ? undefined : { background: stripeColor((point.value - mid) / half, low, high) }}
        title={`${point.year}: ${point.value === null ? 'no data' : `${number(point.value)} ${units}`}`} />)}
    </div>
    <div className="stripe-axis" aria-hidden="true"><span>{first}</span><span>{last}</span></div>
    {values.length > 0 && <p className="stripe-legend">
      <span>{lowLabel} · {number(min)} {units}</span>
      <span className="ramp" aria-hidden="true" style={{ background: `linear-gradient(90deg,${low},rgb(${neutral}),${high})` }} />
      <span>{highLabel} · {number(max)} {units}</span>
      <span className="stripe-note">Colours run from the lowest to the highest year in this record. No baseline or “normal” is implied. Hover a stripe to see its year.</span>
    </p>}
  </figure>;
}
