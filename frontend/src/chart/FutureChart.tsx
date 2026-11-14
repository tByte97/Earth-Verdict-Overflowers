import { useEffect, useRef, useState } from 'react';
import { Chart, Filler, LineController, LineElement, LinearScale, PointElement, type ChartDataset, type Plugin } from 'chart.js';
import type { CheckResult } from '../types';
import { number } from '../format';
import './chart.css';

Chart.register(LineController, LineElement, PointElement, LinearScale, Filler);

type Extrapolation = CheckResult['extrapolation'];
type Scenarios = NonNullable<CheckResult['scenarios']>;

const sspCodes = { ssp126: 'SSP1-2.6', ssp245: 'SSP2-4.5', ssp585: 'SSP5-8.5' };
const sspColors = { ssp126: '#2f7fb8', ssp245: '#b7791f', ssp585: '#b8322f' };
const muted = '#5c7066', grid = '#e7ece4', whatIf = '#245f47';
const lastYear = 2100;

// Shades the future zone right of the last observed year and marks the selected year.
function zones(boundary: number, selected: number): Plugin<'line'> {
  return {
    id: 'zones',
    beforeDatasetsDraw({ ctx, chartArea: area, scales: { x } }) {
      const bx = x.getPixelForValue(boundary), sx = x.getPixelForValue(selected);
      ctx.save();
      ctx.fillStyle = 'rgba(92,112,102,.07)';
      ctx.fillRect(bx, area.top, area.right - bx, area.bottom - area.top);
      ctx.strokeStyle = muted;
      ctx.beginPath(); ctx.moveTo(bx, area.top); ctx.lineTo(bx, area.bottom); ctx.stroke();
      ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.moveTo(sx, area.top); ctx.lineTo(sx, area.bottom); ctx.stroke();
      ctx.restore();
    },
  };
}

function useChart(canvas: React.RefObject<HTMLCanvasElement | null>, datasets: ChartDataset<'line'>[], yTitle: string, xMin: number, plugin: Plugin<'line'>, deps: unknown[]) {
  useEffect(() => {
    if (!canvas.current) return;
    const chart = new Chart(canvas.current, {
      type: 'line',
      data: { datasets },
      plugins: [plugin],
      options: {
        animation: false, responsive: true, maintainAspectRatio: false, events: [],
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
        scales: {
          x: { type: 'linear', min: xMin - 0.5, max: lastYear + 0.5, grid: { color: grid }, ticks: { color: muted, callback: value => String(value) },
            afterBuildTicks: axis => { axis.ticks = Array.from({ length: 6 }, (_, i) => ({ value: 2000 + 20 * i })).filter(tick => tick.value >= xMin); } },
          y: { grid: { color: grid }, ticks: { color: muted }, title: { display: true, text: yTitle, color: muted } },
        },
      },
    });
    return () => chart.destroy();
  }, deps);
}

function Choice<T extends string | number>({ label, options, value, onChange }: { label: string; options: { value: T; text: string; code?: string }[]; value: T; onChange: (value: T) => void }) {
  return <div className="future-choice" role="group" aria-label={label}>
    <span>{label}</span>
    {options.map(option => <button key={option.value} type="button" aria-pressed={option.value === value} onClick={() => onChange(option.value)}>
      {option.text}{option.code && <small>{option.code}</small>}
    </button>)}
  </div>;
}

// B and C read every value from JSON. Scenario values are changes from the baseline period,
// so they get their own panel instead of being added to the absolute observations.
export function FutureChart({ result: r }: { result: CheckResult }) {
  const ext: Extrapolation = r.extrapolation;
  const scen: Scenarios | null = r.scenarios;
  const units = r.variable.units;
  const boundary = r.case.end_year;
  const first = r.series[0]?.year ?? boundary;
  const [extId, setExtId] = useState(ext.paths.find(path => path.id === 'same')?.id ?? ext.paths[0].id);
  const [extYear, setExtYear] = useState(ext.years.at(-1)!);
  const [sspId, setSspId] = useState(scen?.paths.find(path => path.id === 'ssp245')?.id ?? scen?.paths[0]?.id);
  const scenPath = scen?.paths.find(path => path.id === sspId);
  const [sspYear, setSspYear] = useState(scenPath?.years.includes(2050) ? 2050 : scenPath?.years[0]);
  const extPath = ext.paths.find(path => path.id === extId)!;
  const extIndex = ext.years.indexOf(extYear);
  const sspIndex = scenPath && sspYear !== undefined ? scenPath.years.indexOf(sspYear) : -1;

  const topCanvas = useRef<HTMLCanvasElement>(null);
  const bottomCanvas = useRef<HTMLCanvasElement>(null);
  const line = (years: number[], values: number[]) => years.map((year, i) => ({ x: year, y: values[i] }));

  useChart(topCanvas, [
    { label: 'Observed', data: r.series.map(point => ({ x: point.year, y: point.value })), showLine: false, pointRadius: 2.5, pointBackgroundColor: '#5f7d70', borderColor: '#5f7d70' },
    { label: 'What-if low', data: line(ext.years, extPath.low), borderWidth: 0, pointRadius: 0 },
    { label: 'What-if high', data: line(ext.years, extPath.high), borderWidth: 0, pointRadius: 0, fill: '-1', backgroundColor: 'rgba(36,95,71,.14)' },
    ...ext.paths.map(path => ({ label: path.label, data: line(ext.years, path.central), borderColor: path.id === extId ? whatIf : 'rgba(36,95,71,.35)', borderWidth: path.id === extId ? 2.5 : 1.2, borderDash: [6, 4], pointRadius: 0 })),
  ], `${r.variable.label} (${units})`, first, zones(boundary, extYear), [r, extId, extYear]);

  useChart(bottomCanvas, scen && scenPath ? [
    { label: 'Baseline', data: [{ x: first, y: 0 }, { x: lastYear, y: 0 }], borderColor: muted, borderWidth: 1, pointRadius: 0 },
    { label: 'Model low', data: line(scenPath.years, scenPath.low), borderWidth: 0, pointRadius: 0 },
    { label: 'Model high', data: line(scenPath.years, scenPath.high), borderWidth: 0, pointRadius: 0, fill: '-1', backgroundColor: `${sspColors[scenPath.id]}26` },
    ...scen.paths.map(path => ({ label: path.label, data: line(path.years, path.median), borderColor: path.id === sspId ? sspColors[path.id] : `${sspColors[path.id]}66`, borderWidth: path.id === sspId ? 2.5 : 1.2, pointRadius: path.id === sspId ? 4 : 2.5, pointBackgroundColor: sspColors[path.id] })),
  ] : [], `Change (${units})`, first, zones(boundary, sspYear ?? lastYear), [r, sspId, sspYear]);

  return <figure className="future-chart" data-testid="future-chart">
    <figcaption>
      <strong>Looking ahead · not a forecast</strong>
      <span>These lines do not change the verdict above. Choosing a path or a year only changes this view.</span>
    </figcaption>
    <p className="future-zones" aria-hidden="true"><span>Past observations · {first}–{boundary}</span><span>Future · what-if lines and model scenarios</span></p>

    <section className="future-panel" aria-labelledby="future-b">
      <h5 id="future-b">B · If the trend continues <small>what-if line, {ext.from_year}–{ext.years.at(-1)}</small></h5>
      <ul className="chart-legend">
        <li><i className="key-dot" aria-hidden="true" />Observed {r.variable.label.toLowerCase()} ({units})</li>
        <li><i className="key-dash" aria-hidden="true" />What-if lines from the {ext.from_year} trend value ({number(ext.from_value)} {units}); shaded: 95% range of the trend slope for the chosen line</li>
      </ul>
      <div className="future-canvas"><canvas ref={topCanvas} role="img" aria-label={`Observed values and what-if lines to ${ext.years.at(-1)} in ${units}. Exact values are in the readout and the table below.`} /></div>
      <Choice label="Pace" value={extId} onChange={setExtId} options={ext.paths.map(path => ({ value: path.id, text: path.label }))} />
      <label className="future-year">What-if year
        <select value={extYear} onChange={e => setExtYear(Number(e.target.value))}>{ext.years.map(year => <option key={year} value={year}>{year}</option>)}</select>
      </label>
      <p className="future-readout" data-testid="extrapolation-readout" role="status">
        {extYear} · {extPath.label}: <strong>{number(extPath.central[extIndex])} {units}</strong> (95% range {number(extPath.low[extIndex])} to {number(extPath.high[extIndex])} {units})
      </p>
      <p className="future-note">{ext.note}</p>
    </section>

    <section className="future-panel" aria-labelledby="future-c">
      <h5 id="future-c">C · Climate-model scenarios <small>{scen ? `change from the ${scen.baseline_period} average` : 'not available'}</small></h5>
      {scen && scenPath && sspYear !== undefined ? <>
        <ul className="chart-legend">
          <li><i className="key-line key-scenario" aria-hidden="true" />Model median for each emissions path; shaded: model spread (low to high) for the chosen path</li>
          <li><i className="key-zero" aria-hidden="true" />0 = the {scen.baseline_period} average: {number(scen.baseline_value)} {units} (observed)</li>
        </ul>
        <div className="future-canvas"><canvas ref={bottomCanvas} role="img" aria-label={`Model scenarios to ${lastYear} as change from the ${scen.baseline_period} average in ${units}. Exact values are in the readout and the table below.`} /></div>
        <Choice label="Emissions path" value={scenPath.id} onChange={id => { setSspId(id); const next = scen.paths.find(path => path.id === id)!; if (!next.years.includes(sspYear)) setSspYear(next.years[0]); }}
          options={scen.paths.map(path => ({ value: path.id, text: path.label, code: sspCodes[path.id] }))} />
        <Choice label="Scenario year" value={sspYear} onChange={setSspYear} options={scenPath.years.map(year => ({ value: year, text: String(year) }))} />
        <p className="future-readout" data-testid="scenario-readout" role="status">
          {sspYear} · {scenPath.label} <small>{sspCodes[scenPath.id]}</small>: <strong>{number(scenPath.median[sspIndex], true)} {units}</strong> change from the {scen.baseline_period} average (models range {number(scenPath.low[sspIndex], true)} to {number(scenPath.high[sspIndex], true)} {units})
        </p>
        <p className="future-note">{scen.note}</p>
        <p className="future-note">Lines join the model periods; values between them are not model output.</p>
        <p className="future-note">{scen.synthetic ? 'Stylised placeholder curves, not CMIP6 model output.' : `Source: ${scen.source}.`}</p>
      </> : <p className="future-note">No climate-model scenarios for this case.</p>}
    </section>
  </figure>;
}
