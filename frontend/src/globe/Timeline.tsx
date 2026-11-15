import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { css, gradient } from '../colour';
import { coords, formatLimit, seasonName } from './presentation';
import { describe, firstIndex, frameOf, signedAmount, type Frame, type YearCell, type YearView } from './years';
import './timeline.css';

const STEP_MS = 650;

// The years as bars (above the line = higher than usual), a slider over them, and play.
// `index` null means the whole-period trend map is showing and no year is picked.
export function Timeline({ view, index, smooth, onIndex, onSmooth }: {
  view: YearView; index: number | null; smooth: boolean; onIndex: (index: number | null) => void; onSmooth: (smooth: boolean) => void;
}) {
  const { map, lim, pres } = view;
  const means = smooth ? map.mean_smooth : map.mean;
  const first = firstIndex(view, smooth), last = map.years.length - 1;
  // Bar height has its own scale (the largest year fills the track); bar colour keeps the map's scale.
  const tallest = Math.max(...means.map(mean => Math.abs(mean ?? 0))) || 1;
  const [playing, setPlaying] = useState(false);
  const at = useRef(index);
  at.current = index;

  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => {
      const current = at.current ?? first - 1;
      if (current >= last) { setPlaying(false); return; }
      onIndex(Math.max(first, current + 1));
    }, STEP_MS);
    return () => window.clearInterval(id);
  }, [playing, first, last, onIndex]);
  // Another variable or season: stop, the years on screen no longer belong to the running play.
  useEffect(() => setPlaying(false), [view]);

  const play = () => {
    if (playing) { setPlaying(false); return; }
    if (index === null || index >= last) onIndex(first);
    setPlaying(true);
  };
  const pick = (value: number) => { setPlaying(false); onIndex(Math.max(first, value)); };
  const frame = index === null ? null : frameOf(view, index, smooth);
  const labelled = map.years.map((year, i) => i === 0 || i === last || (year % 10 === 0 && i > 2 && i < last - 2));

  return <div className="timeline" data-testid="timeline" data-playing={playing || undefined}>
    <div className="timeline-head">
      <button type="button" className="timeline-play" onClick={play} aria-label={playing ? 'Pause the timeline' : 'Play the years one by one'}>
        <span aria-hidden="true">{playing ? '❚❚' : '▶'}</span>{playing ? 'Pause' : 'Play'}
      </button>
      <span className="timeline-now" data-testid="timeline-now">{frame ? frame.period : `${map.years[0]}–${map.years[last]}: pick a year or press play`}</span>
      <label className="timeline-smooth"><input type="checkbox" checked={smooth} onChange={event => {
        setPlaying(false); onSmooth(event.target.checked);
        if (index !== null) onIndex(Math.max(firstIndex(view, event.target.checked), index));
      }} />{map.window}-year average</label>
      {index !== null && <button type="button" className="timeline-back" onClick={() => { setPlaying(false); onIndex(null); }}>Whole-period trend</button>}
    </div>
    <div className="timeline-track">
      <div className="timeline-bars" aria-hidden="true">{map.years.map((year, i) => {
        const mean = means[i], t = mean === null ? 0 : Math.max(-1, Math.min(1, mean / lim));
        return <i key={year} data-on={i === index || undefined} data-empty={mean === null || undefined}>
          {mean !== null && <b style={{ height: `${Math.max(4, Math.abs(mean) / tallest * 50)}%`, background: css(pres.palette((t + 1) / 2)), ...(t >= 0 ? { bottom: '50%' } : { top: '50%' }) } as CSSProperties} />}
        </i>;
      })}</div>
      <input type="range" aria-label="Year" min={first} max={last} step={1} value={index ?? last}
        aria-valuetext={frame ? describe(frame).headline : 'Whole-period trend'}
        onChange={event => pick(Number(event.target.value))}
        onClick={event => { if (index === null) pick(Number(event.currentTarget.value)); }} />
    </div>
    <div className="timeline-ticks" aria-hidden="true">{map.years.map((year, i) => labelled[i] && <span key={year} style={{ left: `${(i + 0.5) / map.years.length * 100}%` }}>{year}</span>)}</div>
  </div>;
}

export function YearLegend({ frame, variableLabel }: { frame: Frame; variableLabel: string }) {
  const { map, lim, pres } = frame.view;
  return <div className="trend-legend" data-testid="year-legend">
    <span className="trend-legend-title">{seasonName(map.season)} {variableLabel.toLowerCase()} in {frame.period}, {map.units} above or below the {map.baseline[0]}–{map.baseline[1]} average</span>
    <div className="trend-legend-bar" style={{ background: gradient(pres.palette) }} />
    <div className="trend-legend-ends"><span>−{formatLimit(lim)}</span><span>0</span><span>+{formatLimit(lim)}</span></div>
    <div className="trend-legend-note"><div>{pres.down} ◂ ▸ {pres.up}</div></div>
  </div>;
}

export function YearTip({ frame, cell, x, y }: { frame: Frame; cell: YearCell; x: number; y: number }) {
  const value = frame.cells[cell.i], { map, pres } = frame.view;
  return <div className="trend-tip" role="tooltip" style={{ left: Math.min(window.innerWidth - 268, x + 14), top: Math.min(window.innerHeight - 120, y + 14) }}>
    <div className="trend-tip-title">{coords(cell.lat, cell.lon)}</div>
    <div className="trend-tip-row">{frame.period} <b>{value === null ? 'no data' : signedAmount(value, map.units)}</b></div>
    <div className="trend-tip-row trend-tip-small">{value === null ? '' : `${value > 0 ? pres.up : value < 0 ? pres.down : 'same'} than the ${map.baseline[0]}–${map.baseline[1]} average · `}click to investigate</div>
  </div>;
}
