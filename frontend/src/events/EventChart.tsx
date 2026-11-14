import { useEffect, useRef, useState } from 'react';
import type { ProfilePoint } from './schema';

type Series = { month: string; value: number | null }[];
export const ymIndex = (ym: string) => Number(ym.slice(0, 4)) * 12 + Number(ym.slice(5, 7)) - 1;
export const indexYm = (i: number) => `${Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, '0')}`;

const PAD_L = 52, PAD_R = 14;
const verdictColour: Record<string, string> = {
  clear_change: 'var(--ev-clear)', not_significant: 'var(--ev-noise)', placebo_also_changes: 'var(--ev-trend)', too_short: 'var(--ev-missing)', no_placebo: 'var(--ev-missing)',
};

function ticks(lo: number, hi: number, n = 4) {
  if (!Number.isFinite(lo) || !Number.isFinite(hi) || lo === hi) return [lo];
  const step0 = (hi - lo) / n, mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map(f => f * mag).find(s => s >= step0) ?? step0;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toPrecision(10));
  return out;
}
const fmt = (v: number) => Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 1 ? +v.toFixed(2) + '' : +v.toPrecision(2) + '';

function path(points: [number, number | null][]) {
  let d = '', open = false;
  for (const [x, y] of points) {
    if (y === null || !Number.isFinite(y)) { open = false; continue; }
    d += `${open ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`; open = true;
  }
  return d;
}

export function EventChart({ site, control, units, eventMonth, windowYears, profile, onPick }: {
  site: Series; control: Series | null; units: string; eventMonth: string; windowYears: number;
  profile: ProfilePoint[] | null; onPick?: (month: string) => void;
}) {
  const svg = useRef<SVGSVGElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);
  // Draw at the real pixel width so labels stay readable on phones.
  const [W, setW] = useState(760);
  useEffect(() => {
    if (!box.current) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(300, Math.round(e.contentRect.width))));
    ro.observe(box.current);
    return () => ro.disconnect();
  }, []);
  if (!site.length) return null;
  const i0 = ymIndex(site[0].month), i1 = ymIndex(site[site.length - 1].month);
  const x = (i: number) => PAD_L + ((i - i0) / Math.max(1, i1 - i0)) * (W - PAD_L - PAD_R);
  const ev = ymIndex(eventMonth), w = windowYears * 12;

  // Panel A: monthly values
  const A_TOP = 14, A_H = 170;
  const vals = [...site, ...(control ?? [])].map(p => p.value).filter((v): v is number => v !== null);
  const lo = Math.min(...vals), hi = Math.max(...vals), padA = (hi - lo) * 0.06 || 1;
  const ya = (v: number) => A_TOP + A_H - ((v - (lo - padA)) / (hi - lo + 2 * padA)) * A_H;
  const yTicksA = ticks(lo, hi);

  // Panel B: effect if the event were in each month
  const B_TOP = A_TOP + A_H + 46, B_H = 110, STRIP = 12;
  const pts = profile ?? [];
  const eff = pts.flatMap(p => [p.ci_low, p.ci_high, p.effect]).filter((v): v is number => v !== null);
  const blo = Math.min(0, ...eff), bhi = Math.max(0, ...eff), padB = (bhi - blo) * 0.06 || 1;
  const yb = (v: number) => B_TOP + B_H - ((v - (blo - padB)) / (bhi - blo + 2 * padB)) * B_H;
  const band = pts.filter(p => p.ci_low !== null && p.ci_high !== null);
  const bandPath = band.length ? `M${band.map(p => `${x(ymIndex(p.event_month)).toFixed(1)},${yb(p.ci_high!).toFixed(1)}`).join('L')}L${[...band].reverse().map(p => `${x(ymIndex(p.event_month)).toFixed(1)},${yb(p.ci_low!).toFixed(1)}`).join('L')}Z` : '';
  const H = profile ? B_TOP + B_H + STRIP + 34 : A_TOP + A_H + 30;

  const years = [];
  const span = (i1 - i0) / 12, every = span / (W / 90) > 2 ? (span / (W / 90) > 4 ? 8 : 4) : span > 8 ? 2 : 1;
  for (let y = Math.ceil(i0 / 12); y * 12 <= i1; y++) if (y % every === 0) years.push(y);

  function pick(e: React.PointerEvent) {
    if (!onPick || !profile?.length || !svg.current) return;
    const rect = svg.current.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * W;
    const i = Math.round(i0 + ((px - PAD_L) / (W - PAD_L - PAD_R)) * (i1 - i0));
    const first = ymIndex(profile[0].event_month), last = ymIndex(profile[profile.length - 1].event_month);
    onPick(indexYm(Math.min(last, Math.max(first, i))));
  }

  return <div ref={box} className="ev-chart-box"><svg ref={svg} className="ev-chart" viewBox={`0 0 ${W} ${H}`} role="img"
    aria-label={`Monthly ${units} at the site${control ? ' and its surroundings' : ''}, with the before and after windows around ${eventMonth}${profile ? ', and the verdict for every possible event month' : ''}.`}>
    {/* windows */}
    <rect x={x(ev - w)} y={A_TOP} width={x(ev) - x(ev - w)} height={A_H} className="ev-before" />
    <rect x={x(ev)} y={A_TOP} width={x(ev + w) - x(ev)} height={A_H} className="ev-after" />
    {x(ev) - x(ev - w) > 56 && <text x={(x(ev - w) + x(ev)) / 2} y={A_TOP + 12} className="ev-window-label" textAnchor="middle">before</text>}
    {x(ev + w) - x(ev) > 56 && <text x={(x(ev) + x(ev + w)) / 2} y={A_TOP + 12} className="ev-window-label" textAnchor="middle">after</text>}
    {yTicksA.map(t => <g key={t}><line x1={PAD_L} x2={W - PAD_R} y1={ya(t)} y2={ya(t)} className="ev-grid" /><text x={PAD_L - 6} y={ya(t) + 3} textAnchor="end" className="ev-tick">{fmt(t)}</text></g>)}
    {control && <path d={path(control.map(p => [x(ymIndex(p.month)), p.value === null ? null : ya(p.value)]))} className="ev-line-control" />}
    <path d={path(site.map(p => [x(ymIndex(p.month)), p.value === null ? null : ya(p.value)]))} className="ev-line-site" />
    <line x1={x(ev)} x2={x(ev)} y1={A_TOP} y2={profile ? B_TOP + B_H + STRIP : A_TOP + A_H} className="ev-cursor" />
    <text x={PAD_L - 6} y={A_TOP + A_H + 16} className="ev-axis-title" textAnchor="end">{units}</text>
    {years.map(y => <text key={y} x={x(y * 12)} y={A_TOP + A_H + 16} textAnchor="middle" className="ev-tick">{y}</text>)}

    {profile && <g>
      <text x={PAD_L} y={B_TOP - 10} className="ev-panel-title">{W < 560 ? 'Change if the event were in each month' : 'If the event were in this month · change vs surroundings, 95% interval'}</text>
      {ticks(blo, bhi, 3).map(t => <g key={t}><line x1={PAD_L} x2={W - PAD_R} y1={yb(t)} y2={yb(t)} className={t === 0 ? 'ev-zero' : 'ev-grid'} /><text x={PAD_L - 6} y={yb(t) + 3} textAnchor="end" className="ev-tick">{t > 0 ? '+' : ''}{fmt(t)}</text></g>)}
      <path d={bandPath} className="ev-band" />
      <path d={path(pts.map(p => [x(ymIndex(p.event_month)), p.effect === null ? null : yb(p.effect)]))} className="ev-line-effect" />
      {pts.map(p => <rect key={p.event_month} x={x(ymIndex(p.event_month)) - (W - PAD_L - PAD_R) / Math.max(1, i1 - i0) / 2} y={B_TOP + B_H + 4}
        width={(W - PAD_L - PAD_R) / Math.max(1, i1 - i0) + 0.4} height={STRIP} fill={verdictColour[p.reason]} />)}
      <rect x={PAD_L} y={B_TOP} width={W - PAD_L - PAD_R} height={B_H + STRIP + 4} className="ev-hit"
        onPointerDown={e => { dragging.current = true; e.currentTarget.setPointerCapture(e.pointerId); pick(e); }}
        onPointerMove={e => { if (dragging.current) pick(e); }}
        onPointerUp={() => { dragging.current = false; }} onPointerCancel={() => { dragging.current = false; }} />
    </g>}
  </svg></div>;
}
