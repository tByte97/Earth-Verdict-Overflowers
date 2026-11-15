import type { CheckResult } from './types';
import { TermHelp } from './TermHelp';
import { chanceInWords, coords, number, period, seasonName, sourceIndex } from './format';

const verdicts = { confirmed: 'Confirmed', refuted: 'Refuted', not_proven: 'Not proven' };
const reasons: Record<string, string> = {
  significant_trend: 'The evidence supports the direction of change in your claim.',
  opposite_trend: 'The evidence shows a trend in the opposite direction to your claim.',
  not_significant: 'The trend is not clear enough to distinguish from year-to-year variation.',
  short_series: 'There are too few observations to establish a reliable trend.',
  sources_disagree: 'The two data sources disagree about the direction of change.',
  not_robust: 'The conclusion depends too much on which years are selected.',
  no_variation: 'The value never changes here in this season, so there is no trend to test.',
};

// Warnings come from backend fields only. Source disagreement is one warning, whether it
// arrives as the reason or as the station agreement.
function warnings(r: CheckResult, source = 'main') {
  const out: string[] = [];
  if (r.reason === 'sources_disagree' || r.witness?.agreement === 'disagree') out.push(`The ground station${r.witness ? ` ${r.witness.station.name}` : ''} and the ${source} record disagree about this trend.`);
  if (r.reason === 'not_robust') out.push('The result changes when the first or last years are shifted, so it is not robust.');
  if (r.reason === 'short_series') out.push('The record is too short for a reliable trend test.');
  return out;
}

// The top of the result: every value is read from the CheckResult as returned.
export function VerdictHero({ result: r }: { result: CheckResult }) {
  const place = r.case.place;
  const region = place.place_id.startsWith('region:');
  const live = place.place_id.startsWith('pt:');
  const source = r.provenance[sourceIndex('series', r) ?? -1]?.source;
  const where = [place.name, ...(region ? [] : [coords(place.lat, place.lon), live ? `live from ${source ?? 'the backend'}` : '~50 km cell'])].join(' · ');
  const first = r.sen.band[0], last = r.sen.band.at(-1);
  const alpha = r.detection_history?.alpha;
  const emerged = r.detection_history?.emerged_year;
  const units = r.variable.units;
  const season = r.case.season === 'year' ? 'yearly' : typeof r.case.season === 'number' ? seasonName(r.case.season) : seasonName(r.case.season).toLowerCase();
  return <div className="hero">
    <p className="where">{where}</p>
    <span className="eyebrow">Rate of change · Sen’s slope · {period(r)} <TermHelp term="trend" /></span>
    <div className="metric-value">{number(r.sen.slope_per_decade, true)}<span>{units} per decade</span></div>
    <section className={`verdict verdict-${r.verdict}`} aria-label="Verdict">
      <h3>{verdicts[r.verdict]}</h3>
      <p>{reasons[r.reason] ?? 'The backend returned an unrecognised reason. Inspect the response details.'}</p>
    </section>
    <p className="hero-text">
      {first && last && <>From {first.year} to {last.year}, {season} {r.variable.label.toLowerCase()} here went from about <b>{number(first.mid)}</b> to <b>{number(last.mid)} {units}</b>. </>}
      {alpha !== undefined && chanceInWords(r.mk.p, alpha)}
    </p>
    {r.verdict === 'not_proven' && <p className="hero-text">
      {(r.reason === 'not_significant' || r.reason === 'short_series') && 'The evidence does not show a real trend yet. '}Not proven does not mean no change.
      {r.years_to_wait !== null && <> At the observed rate, about <b>{number(r.years_to_wait)} more years</b> of observations may be needed to tell.</>}
    </p>}
    <dl className="facts">
      <div className="fact"><dt>p-value</dt><dd>{number(r.mk.p)}</dd></div>
      <div className="fact"><dt>95% range, per decade</dt><dd>{number(r.sen.ci_low, true)} … {number(r.sen.ci_high, true)} {units}</dd></div>
      <div className="fact"><dt>Signal emerged</dt><dd>{emerged ?? '—'}</dd></div>
    </dl>
    {warnings(r, source).map(text => <p className="warn" key={text}>{text}</p>)}
  </div>;
}
