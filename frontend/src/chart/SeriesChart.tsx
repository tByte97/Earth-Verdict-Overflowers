import { useEffect, useRef, useState } from 'react';
import { Chart, LineController, LineElement, LinearScale, PointElement } from 'chart.js';
import type { CheckResult } from '../types';
import { number, period, safeUrl, sourceIndex } from '../format';
import './chart.css';

Chart.register(LineController, LineElement, PointElement, LinearScale);

const colors = { series: '#245f47', trend: '#c2410c', station: '#3a6fc4', grid: '#e7ece4', muted: '#5c7066' };
const seasonNames: Record<string, string> = { year: 'whole-year', DJF: 'winter (Dec–Feb)', MAM: 'spring (Mar–May)', JJA: 'summer (Jun–Aug)', SON: 'autumn (Sep–Nov)' };
const seasonName = (season: CheckResult['case']['season']) => typeof season === 'number'
  ? new Intl.DateTimeFormat('en', { month: 'long' }).format(new Date(2000, season - 1, 1))
  : seasonNames[season];

function SourceLink({ result: r, path, children }: { result: CheckResult; path: string; children: string }) {
  const index = sourceIndex(path, r);
  const url = index === undefined ? undefined : safeUrl(r.provenance[index].url);
  return url ? <a href={url} target="_blank" rel="noreferrer">{children} <span aria-hidden="true">↗</span></a> : <>{children}</>;
}

// Draws only supplied values. The trend line uses the contract formula
// intercept + slope_per_year × (year − start_year) at the two period ends.
export function SeriesChart({ result: r }: { result: CheckResult }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [hover, setHover] = useState<{ year: number; left: number; flip: boolean } | null>(null);
  const units = r.variable.units;
  const witness = r.witness;
  const station = new Map(witness?.series.map(point => [point.year, point.value]) ?? []);
  const years = r.series.map(point => point.year);
  const first = years[0], last = years.at(-1)!;

  useEffect(() => {
    const node = canvas.current;
    if (!node) return;
    const trend = [r.case.start_year, r.case.end_year].map(year => ({ x: year, y: r.sen.intercept + r.sen.slope_per_year * (year - r.case.start_year) }));
    const chart = new Chart(node, {
      type: 'line',
      data: { datasets: [
        { label: 'NASA POWER', data: r.series.map(p => ({ x: p.year, y: p.value })), showLine: false, pointRadius: 3, pointBackgroundColor: colors.series, borderColor: colors.series },
        { label: 'Trend', data: trend, borderColor: colors.trend, borderWidth: 2.5, pointRadius: 0 },
        ...(witness ? [{ label: 'Station', data: years.map(year => ({ x: year, y: station.get(year) ?? null })), spanGaps: false, borderColor: colors.station, borderWidth: 1.5, pointStyle: 'triangle' as const, pointRadius: 3, pointBackgroundColor: colors.station }] : []),
      ] },
      options: {
        animation: false, responsive: true, maintainAspectRatio: false,
        events: ['mousemove', 'mouseout', 'touchstart', 'touchmove'],
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
        scales: {
          x: { type: 'linear', min: first - 0.5, max: last + 0.5, grid: { color: colors.grid }, ticks: { color: colors.muted, callback: value => Number.isInteger(value) ? String(value) : '' },
            title: { display: true, text: `Year · ${seasonName(r.case.season)} values`, color: colors.muted } },
          y: { grid: { color: colors.grid }, ticks: { color: colors.muted }, title: { display: true, text: `${r.variable.label} (${units})`, color: colors.muted } },
        },
        onHover: (event, _elements, instance) => {
          if (event.x == null) return;
          const year = Math.round(instance.scales.x.getValueForPixel(event.x) ?? NaN);
          const left = instance.scales.x.getPixelForValue(year);
          setHover(year >= first && year <= last ? { year, left, flip: left > instance.width / 2 } : null);
        },
      },
    });
    // onHover only fires inside the plot area, so leaving the canvas clears the tooltip here.
    const leave = () => setHover(null);
    node.addEventListener('mouseleave', leave);
    return () => { node.removeEventListener('mouseleave', leave); chart.destroy(); };
  }, [r]);

  const value = hover && r.series.find(point => point.year === hover.year)?.value;
  const stationValue = hover && station.get(hover.year);
  return <figure className="series-chart" data-testid="series-chart">
    <figcaption>Yearly {seasonName(r.case.season)} values, {period(r)} · absolute values in {units}, no baseline</figcaption>
    <ul className="chart-legend">
      <li><i className="key-dot" aria-hidden="true" />NASA POWER reanalysis · one point per year ({units})</li>
      <li><i className="key-line" aria-hidden="true" />Trend (Sen’s slope): {number(r.sen.slope_per_decade, true)} {units} / decade over {period(r)}</li>
      <li className="legend-range">95% range for this rate: {number(r.sen.ci_low, true)} to {number(r.sen.ci_high, true)} {units} / decade. The shaded band is not drawn yet: the backend does not supply its outline.</li>
      <li>{witness ? <><i className="key-station" aria-hidden="true" />Ground station {witness.station.name}, {number(witness.station.distance_km)} km away ({units}). Breaks in the line are years with no station measurement.</> : 'No ground station for this place. Only the NASA POWER series is shown.'}</li>
    </ul>
    <div className="chart-canvas">
      <canvas ref={canvas} role="img" aria-label={`Chart of ${r.variable.label} in ${units} for ${period(r)}. Exact values are in the table below.`} />
      {hover && <div className="chart-tooltip" role="status" data-testid="chart-tooltip" style={{ left: hover.left, transform: hover.flip ? 'translateX(calc(-100% - 8px))' : 'translateX(8px)' }}>
        <strong>{hover.year}</strong>
        <span>NASA POWER: {value == null ? 'no data' : `${number(value)} ${units}`}</span>
        <span>Station: {!witness ? 'none for this place' : stationValue == null ? 'no station measurement' : `${number(stationValue)} ${units}`}</span>
      </div>}
    </div>
    <details className="chart-values">
      <summary>Exact values for every year <span>Received precision · missing values stay missing</span></summary>
      <div className="table-scroll numeric-table"><table>
        <thead><tr><th>Year</th><th><SourceLink result={r} path="series.0.value">NASA POWER</SourceLink> · {units}</th><th>{witness ? <><SourceLink result={r} path="witness.series.0.value">{`Station ${witness.station.name}`}</SourceLink> · {units}</> : 'Station'}</th></tr></thead>
        <tbody>{r.series.map(point => {
          const measured = station.get(point.year);
          return <tr key={point.year}><th>{point.year}</th><td>{point.value === null ? 'no data' : String(point.value)}</td><td>{!witness ? 'no station for this place' : measured == null ? 'no station measurement' : String(measured)}</td></tr>;
        })}</tbody>
      </table></div>
    </details>
  </figure>;
}
