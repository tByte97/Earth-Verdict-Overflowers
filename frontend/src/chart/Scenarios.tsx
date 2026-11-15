import type { CheckResult } from '../types';
import { number } from '../format';
import { palette, seasonName } from './ramp';

export type ScenarioPath = NonNullable<CheckResult['scenarios']>['paths'][number];
export const SSP: Record<ScenarioPath['id'], { code: string; color: string }> = {
  ssp126: { code: 'SSP1-2.6', color: '#7fb3d5' },
  ssp245: { code: 'SSP2-4.5', color: '#e0b45c' },
  ssp585: { code: 'SSP5-8.5', color: '#e8705a' },
};

const ordinal = (n: number) => `${n}${n % 100 >= 11 && n % 100 <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[n % 10] ?? 'th'}`;
const span = (window: string) => window.replace('-', '–');

// Picks the backend's analog for the node and words it; nothing is ranked or compared here.
export function analogSentence(r: CheckResult, path: ScenarioPath, i: number) {
  const a = path.analogs[i];
  const typical = r.case.season === 'year' ? 'A typical year' : typeof r.case.season === 'number' ? `A typical ${seasonName(r.case.season)}` : `A typical ${seasonName(r.case.season).toLowerCase()}`;
  if (a.beyond_record) return `${typical} around ${a.year} would be beyond anything in the ${r.case.start_year}–${r.case.end_year} record.`;
  if (a.analog_year === null || a.analog_value === null || a.analog_rank === null) return `There is no observed year to compare ${a.year} with.`;
  const most = palette(r.variable.id).most;
  return `${typical} around ${a.year} would be like ${a.analog_year} (${number(a.analog_value)} ${r.variable.units}), the ${a.analog_rank === 1 ? most : `${ordinal(a.analog_rank)} ${most}`} on record.`;
}

export function ScenarioPanel({ result: r, path, node, onPath, onNode }: {
  result: CheckResult; path: ScenarioPath; node: number; onPath: (path: ScenarioPath) => void; onNode: (year: number) => void;
}) {
  const scen = r.scenarios!;
  const units = r.variable.units;
  const i = path.years.indexOf(node);
  return <section className="scenarios" aria-label="Future scenarios" data-testid="scenarios">
    <h4>Future scenarios <span>right of “now” on the chart</span></h4>
    <div className="scenario-choice" role="group" aria-label="Emissions path">
      {scen.paths.map(p => <button key={p.id} type="button" aria-pressed={p.id === path.id} onClick={() => onPath(p)}>
        <i style={{ background: SSP[p.id].color }} aria-hidden="true" />{p.label} <small>{SSP[p.id].code}</small>
      </button>)}
    </div>
    <div className="scenario-choice" role="group" aria-label="Scenario year">
      {path.years.map(year => <button key={year} type="button" aria-pressed={year === node} onClick={() => onNode(year)}>{year}</button>)}
    </div>
    <p className="scenario-window" data-testid="scenario-window">{node} = average of {span(path.windows[i])}</p>
    <p className="scenario-readout" role="status" aria-live="polite" data-testid="scenario-readout">
      {path.label} <small>{SSP[path.id].code}</small>, {node}: median <b>{number(path.median_value[i])} {units}</b>, models {number(path.low_value[i])} to {number(path.high_value[i])} {units}
    </p>
    <p className="scenario-analog" data-testid="scenario-analog">{analogSentence(r, path, i)}</p>
    <p className="scenario-disclaimer"><strong>Climate-model scenarios, not a weather forecast.</strong> Choosing a scenario does not change the verdict about the past.</p>
    <p className="scenario-source">
      {scen.synthetic ? 'Stylised placeholder curves, not CMIP6 model output. ' : ''}Source: {scen.source}. Scenario baseline: {scen.baseline_period} average, {number(scen.baseline_value)} {units}. {scen.note} Lines join the model periods; values between them are not model output.
    </p>
  </section>;
}
