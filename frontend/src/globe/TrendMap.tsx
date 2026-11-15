import { colourLimit, gridOf, type Grid } from './paint';
import { gradient } from '../colour';
import { bySeason, commonDirection, coords, formatLimit, formatP, presentationOf, seasonName, signed, type Presentation } from './presentation';
import type { LayerEntry, PairEnd, TrendCell, TrendLayer } from './trends';
import './trend-map.css';

// Everything the globe, legend and callout need to draw one layer, prepared once per layer.
// `cells` is everything painted; `core` is the tested area, which the scale, the dots and the words are read from.
export interface TrendView { layer: TrendLayer; grid: Grid; cells: TrendCell[]; core: TrendCell[]; lim: number; pres: Presentation }
export function trendView(layer: TrendLayer): TrendView {
  const cells = layer.features.map(feature => feature.properties);
  const core = cells.filter(cell => !cell.halo);
  return { layer, grid: gridOf(cells), cells, core, lim: colourLimit(core), pres: presentationOf(layer.variable_id) };
}

export function TrendLegend({ view, fade, variableLabel }: { view: TrendView; fade: boolean; variableLabel: string }) {
  const { layer, lim, pres } = view;
  return <div className="trend-legend" data-testid="trend-legend">
    <span className="trend-legend-title">{seasonName(layer.season)} {variableLabel.toLowerCase()} trend, {layer.units_per_decade}</span>
    <div className="trend-legend-bar" style={{ background: gradient(pres.palette) }} />
    <div className="trend-legend-ends"><span>−{formatLimit(lim)}</span><span>0</span><span>+{formatLimit(lim)}</span></div>
    <div className="trend-legend-note">
      <div><i aria-hidden="true" />dots = significant after FDR (q = {layer.q})</div>
      {fade && <div>white = could be chance (noise)</div>}
      <div>{pres.down} ◂ ▸ {pres.up}</div>
    </div>
  </div>;
}

// The share is printed only when the backend sends the counts; the browser never counts cells itself.
export function TrendCaption({ layer }: { layer: TrendLayer }) {
  if (layer.n_cells === undefined || layer.n_significant_fdr === undefined || !layer.n_cells) return null;
  return <p className="trend-caption">{Math.round(layer.n_significant_fdr / layer.n_cells * 100)}% of cells over Ukraine show a significant trend after FDR · chance alone would give ~{layer.q * 100}%</p>;
}

export function CellTip({ view, cell, x, y }: { view: TrendView; cell: TrendCell; x: number; y: number }) {
  return <div className="trend-tip" role="tooltip" style={{ left: Math.min(window.innerWidth - 268, x + 14), top: Math.min(window.innerHeight - 120, y + 14) }}>
    <div className="trend-tip-title">{coords(cell.lat, cell.lon)}</div>
    <div className="trend-tip-row">Trend <b>{signed(cell.slope_per_decade)} {view.layer.units_per_decade}</b></div>
    <div className="trend-tip-row">p <b>{formatP(cell.p)}</b></div>
    <div className="trend-tip-row trend-tip-small">{cell.significant_fdr ? 'significant' : 'could be chance'}{cell.halo ? ' · outside the Ukraine area' : ''} · click to investigate</div>
  </div>;
}

export interface LayerKey { variable_id: string; season: string }

function fadeDisableReason(layer: TrendLayer | null): string | null {
  if (!layer) return 'No trend map is loaded.';
  const tested = layer.features.filter(f => !f.properties.halo);
  const total = layer.n_cells ?? tested.length;
  const sig = layer.n_significant_fdr ?? tested.filter(f => f.properties.significant_fdr).length;
  if (sig === 0) return 'No cells are significant after FDR.';
  if (total > 0 && sig >= total) return 'Every cell is significant after FDR.';
  return null;
}

// Variable and season choices come from the layer index; without an index only the fade switch is offered.
export function LayerControls({ index, value, layer, onChange, fade, onFade, labelOf }: {
  index: LayerEntry[] | null | undefined; value: LayerKey | null; layer: TrendLayer | null;
  onChange: (key: LayerKey) => void; fade: boolean; onFade: (fade: boolean) => void; labelOf: (variableId: string) => string;
}) {
  const variables = index ? [...new Set(index.map(entry => entry.variable_id))] : [];
  const activeVar = value && variables.includes(value.variable_id) ? value.variable_id : variables[0];
  const seasons = index && activeVar ? index.filter(entry => entry.variable_id === activeVar).map(entry => entry.season).sort(bySeason) : [];
  const fadeReason = fadeDisableReason(layer);
  const choose = (variable_id: string, season: string) => {
    const available = index!.filter(entry => entry.variable_id === variable_id);
    onChange({ variable_id, season: available.some(entry => entry.season === season) ? season : available[0].season });
  };
  return <div className="trend-controls">
    {variables.length > 0 && <>
      <div className="trend-eyebrow">What to measure</div>
      <div className="trend-seg" role="group" aria-label="Trend map variable">{variables.map(id =>
        <button key={id} type="button" aria-pressed={value?.variable_id === id} onClick={() => choose(id, value?.season ?? '')}>{labelOf(id)}</button>)}</div>
      {seasons.length > 0 && <>
        <div className="trend-eyebrow">Season</div>
        <div className="trend-seg" role="group" aria-label="Trend map season">{seasons.map(season =>
          <button key={season} type="button" aria-pressed={value?.variable_id === activeVar && value?.season === season} onClick={() => choose(activeVar, season)}>{seasonName(season)}</button>)}</div>
      </>}
    </>}
    <label className="trend-check" title={fadeReason ?? undefined}>
      <input type="checkbox" checked={fade} disabled={!!fadeReason} aria-describedby={fadeReason ? 'fade-reason' : undefined} onChange={event => onFade(event.target.checked)} />
      Fade trends that could be chance
    </label>
    {fadeReason && <p className="field-help trend-check-note" id="fade-reason">{fadeReason}</p>}
  </div>;
}

const pairLine = (end: PairEnd, word: string, units: string) =>
  <><b>{word}</b> around {coords(end.lat, end.lon)} ({signed(end.slope_per_decade)} {units}, p {end.p < 0.001 ? '<0.001' : `= ${end.p}`})</>;

export function PairCallout({ view, variableLabel }: { view: TrendView; variableLabel: string }) {
  const { layer, pres, core: cells } = view;
  const subject = `${layer.season === 'year' ? 'Year-round' : seasonName(layer.season)} ${variableLabel.toLowerCase()}`;
  if (!layer.pair) {
    const direction = commonDirection(cells);
    return <div className="trend-callout" data-testid="pair-callout">
      <b>No opposite trends here:</b> {direction ? `every significant cell ${direction === 'up' ? pres.upVerb : pres.downVerb}.` : 'the backend found no pair of significant cells moving in opposite directions.'}
    </div>;
  }
  const { a, b, distance_km, significance } = layer.pair;
  const word = (end: PairEnd) => (end.slope_per_decade > 0 ? pres.up : pres.down);
  return <div className="trend-callout" data-testid="pair-callout">
    <b>Opposite trends.</b> {subject} is getting {pairLine(a, word(a), layer.units_per_decade)} and {pairLine(b, word(b), layer.units_per_decade)}. The two spots are {distance_km} km apart.
    {' '}{significance === 'fdr' ? `Both are significant after FDR (q = ${layer.q}).` : 'This pair is significant on raw p-values only, not after FDR.'}
    {pres.driver && <><br /><br /><b>Possible common driver:</b> {pres.driver}</>}
  </div>;
}
