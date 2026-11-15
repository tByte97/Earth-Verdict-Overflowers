// One colour scale for the trend map and the record chart: OKLab interpolation keeps diverging ramps
// perceptually even on both sides of zero. Colours and display scales only; no statistics here.
export type Rgb = [number, number, number];
const toLin = (c: number) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const fromLin = (c: number) => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);
function hexToLab(hex: string): Rgb {
  const [r, g, b] = [1, 3, 5].map(i => toLin(parseInt(hex.slice(i, i + 2), 16) / 255));
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s];
}
function labToRgb([L, a, b]: Rgb): Rgb {
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  return [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s]
    .map(c => Math.round(255 * Math.min(1, Math.max(0, fromLin(c))))) as Rgb;
}
export type Ramp = (t: number) => Rgb;
export function ramp(stops: string[]): Ramp {
  const labs = stops.map(hexToLab);
  return t => {
    t = Math.min(1, Math.max(0, t)) * (labs.length - 1);
    const i = Math.min(labs.length - 2, Math.floor(t)), f = t - i;
    return labToRgb(labs[i].map((v, k) => v + (labs[i + 1][k] - v) * f) as Rgb);
  };
}
export const css = ([r, g, b]: Rgb) => `rgb(${r},${g},${b})`;
export const gradient = (fn: Ramp, n = 12) => `linear-gradient(90deg, ${Array.from({ length: n }, (_, i) => css(fn(i / (n - 1)))).join(',')})`;

// A nice display step (1, 2, 2.5, 5 × 10ⁿ) for legend limits and axis grid lines.
export function niceStep(x: number) {
  const e = 10 ** Math.floor(Math.log10(x)), f = x / e;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * e;
}

// Diverging ramp per variable_id: two hues meeting at a neutral grey ("no change"), with the words for both ends.
export interface VariableColours { ramp: Ramp; up: string; down: string; most: string }
const warm: VariableColours = { ramp: ramp(['#72a9ee', '#36629e', '#3b3a37', '#b1483d', '#f28466']), up: 'warmer', down: 'cooler', most: 'warmest' };
const wet: VariableColours = { ramp: ramp(['#c9914f', '#7d5b31', '#3b3a37', '#2c7b73', '#63c7b8']), up: 'wetter', down: 'drier', most: 'wettest' };
const colours: Record<string, VariableColours> = {
  air_temp: warm,
  global_temp: warm,
  precip: wet,
  snow_depth: { ramp: ramp(['#b9824a', '#6e4f2f', '#3b3a37', '#4a7fac', '#c4e3f6']), up: 'more snow', down: 'less snow', most: 'snowiest' },
};
// A variable the frontend has no words for still renders, on a neutral ramp.
const neutral: VariableColours = { ramp: ramp(['#7c8aa0', '#4a5262', '#3b3a37', '#6a6250', '#b3a789']), up: 'higher', down: 'lower', most: 'highest' };
export const coloursOf = (variableId: string) => colours[variableId] ?? neutral;
