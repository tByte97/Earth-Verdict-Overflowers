import type { CheckResult } from '../types';
import { coloursOf, css } from '../colour';

export { niceStep } from '../colour';

// Chart view of the shared colour scale: CSS colours for SVG fills.
export const palette = (variableId: string) => {
  const { ramp, down, up, most } = coloursOf(variableId);
  return { pal: (t: number) => css(ramp(t)), down, up, most };
};

const seasons: Record<string, string> = { year: 'Annual', DJF: 'Winter', MAM: 'Spring', JJA: 'Summer', SON: 'Autumn' };
export const seasonName = (season: CheckResult['case']['season']) => typeof season === 'number'
  ? new Intl.DateTimeFormat('en', { month: 'long' }).format(new Date(2000, season - 1, 1))
  : seasons[season];

// The colour of the trend line: the "up" or "down" end of the variable's ramp.
export const trendColor = (r: CheckResult) => palette(r.variable.id).pal(r.sen.slope_per_decade > 0 ? 0.92 : 0.08);
