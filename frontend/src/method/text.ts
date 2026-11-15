// Every sentence of "How the detective decides" lives here, so the plain-language glossary can replace
// them in one place. Only methods the backend actually runs; no numbers that are not in a response.
export interface MethodStep { id: string; title: string; body: string }

export const methodIntro = 'The same steps run for every claim and every spot. The browser only shows the results; every number comes from the backend.';

export const methodSteps: MethodStep[] = [
  {
    id: 'season',
    title: 'One number per year',
    body: 'From the monthly record we keep only the months of the chosen season and turn them into one value per year: an average or a total, depending on the variable. A year with a missing month is left out, never filled in.',
  },
  {
    id: 'sen',
    title: 'How fast: Sen’s slope',
    body: 'We take the slope between every pair of years and use the middle one, so a few wild years cannot decide the answer. Its 95% range shows how fast the change could plausibly be.',
  },
  {
    id: 'mann-kendall',
    title: 'Could it be chance: Mann–Kendall',
    body: 'For every pair of years we check whether the later one is higher or lower and count which happens more often. Neighbouring years tend to resemble each other, which can make chance look like a trend; the Hamed–Rao correction accounts for this year-to-year memory.',
  },
  {
    id: 'robustness',
    title: 'Does the choice of years matter?',
    body: 'We repeat the check with the start and end shifted by a few years. A trend that appears only for one lucky choice of years is not called confirmed.',
  },
  {
    id: 'witness',
    title: 'A second witness: the ground station',
    body: 'Where a NOAA station is close enough, we compare how fast it and the reanalysis change, using the difference between the two over the years they share. Gaps in the station record stay gaps.',
  },
  {
    id: 'fdr',
    title: 'On the map: many tests at once',
    body: 'Testing hundreds of cells, some would look significant by chance alone. Dots mark cells that stay significant after the false discovery rate correction (Benjamini–Hochberg); faded cells could be chance.',
  },
  {
    id: 'verdict',
    title: 'Three verdicts',
    body: 'Confirmed: a clear, robust trend in the claimed direction. Refuted: a clear trend the other way. Not proven: the evidence is not yet strong enough against normal year-to-year variation. Not proven does not mean no change.',
  },
  {
    id: 'limits',
    title: 'Limits',
    body: 'MERRA-2 is a reanalysis: a weather model kept on track by observations, not a thermometer at this spot. Snow depth and soil moisture come from its land model, not from direct measurements. A grid cell covers a wide area, so local effects such as a city’s heat island can differ.',
  },
];
