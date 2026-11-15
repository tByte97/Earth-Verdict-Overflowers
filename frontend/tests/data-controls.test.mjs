import { test, expect } from '@playwright/test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const readJson = async path => JSON.parse(await readFile(new URL(path, import.meta.url), 'utf8'));
const heat = await readJson('../../data/cases/kyiv-summer-heat.json');
const stopped = await readJson('../../data/cases/global-warming-stopped.json');
const gpm = await readJson('../../data/cases/kyiv-summer-rain-gpm.json');
const ny = await readJson('../../data/cases/newyork-winter-warming.json');
const evSites = await readJson('../../data/events/_sites.json');
const laNo2 = await readJson('../../data/events/la-no2-lockdown.json');

const REGIONS = [
  { place_id: 'region:globe', name: 'The whole planet', lat: 0, lon: 0 },
  { place_id: 'region:europe', name: 'Europe', lat: 50, lon: 15 },
  { place_id: 'region:asia', name: 'Asia', lat: 45, lon: 90 },
  { place_id: 'region:africa', name: 'Africa', lat: 5, lon: 20 },
  { place_id: 'region:northamerica', name: 'North America', lat: 45, lon: -100 },
  { place_id: 'region:southamerica', name: 'South America', lat: -15, lon: -60 },
  { place_id: 'region:oceania', name: 'Oceania', lat: -25, lon: 135 },
  { place_id: 'region:arctic', name: 'The Arctic', lat: 80, lon: 0 },
];

const VARIABLES = [
  { ...heat.variable, first_year: 1981, last_year: 2025 },
  { ...gpm.variable, first_year: 1998, last_year: 2024 },
  { ...stopped.variable, first_year: 1850, last_year: 2025 },
];

test('missing trend layer case shows calm note, keeps season chips, disables Fade and explains disabled Local view', async ({ page }) => {
  const errors = [];
  page.on('pageerror', e => errors.push(e.stack || e.message));
  await page.route('https://gibs.earthdata.nasa.gov/**', route => route.abort());
  await page.goto('/?source=saved#case=global-warming-stopped');

  await expect(page.getByRole('heading', { name: 'Refuted', exact: true })).toBeVisible();
  await expect(page.locator('.trend-status')).toContainText('No trend map for temperature of the planet or a continent (whole year). Trend maps cover air temperature and precipitation over Ukraine, for the year, summer and winter.');
  await expect(page.locator('.trend-status')).not.toContainText('Trend map unavailable');
  await expect(page.getByRole('group', { name: 'Trend map season' }).getByRole('button')).toHaveCount(3);
  await expect(page.getByLabel('Fade trends that could be chance')).toBeDisabled();
  await expect(page.locator('#fade-reason')).toHaveText('No trend map is loaded.');
  const localBtn = page.getByRole('button', { name: 'Local view' });
  await expect(localBtn).toBeDisabled();
  await expect(localBtn).toHaveAttribute('title', 'Pick a city or a point to zoom in; regions have no local view');
  await expect(localBtn).toHaveAttribute('aria-description', 'Pick a city or a point to zoom in; regions have no local view');
  await expect(page.locator('button[aria-pressed="true"]').filter({ hasText: 'Global warming' })).toBeVisible();
  assert.deepEqual(errors, []);
});

test('opening global-warming-stopped in live mode never requests an invalid grid layer and reports Ukraine grid extent on US cases', async ({ page }) => {
  const errors = [];
  const gridRequests = [];
  page.on('pageerror', e => errors.push(e.stack || e.message));
  await page.route('https://gibs.earthdata.nasa.gov/**', route => route.abort());
  await page.route('**/api/variables', route => route.fulfill({ json: VARIABLES }));
  await page.route('**/api/regions', route => route.fulfill({ json: REGIONS }));
  await page.route('**/api/cases', route => route.fulfill({ json: [
    { id: 'global-warming-stopped', claim_text: stopped.case.claim_text, place: stopped.case.place.name, variable_id: stopped.case.variable_id, verdict: stopped.verdict },
    { id: 'newyork-winter-warming', claim_text: ny.case.claim_text, place: ny.case.place.name, variable_id: ny.case.variable_id, verdict: ny.verdict },
  ] }));
  await page.route('**/api/cases/global-warming-stopped', route => route.fulfill({ json: stopped }));
  await page.route('**/api/cases/newyork-winter-warming', route => route.fulfill({ json: ny }));
  await page.route('**/api/grid/index', route => route.fulfill({ json: [
    { variable_id: 'air_temp', season: 'DJF', start_year: 1982, end_year: 2025, units_per_decade: '°C/decade' },
  ] }));
  await page.route('**/api/grid?*', async route => {
    gridRequests.push(route.request().url());
    const gj = JSON.parse(await readFile(new URL('../../data/layers/trends_T2M_DJF.geojson', import.meta.url), 'utf8'));
    return route.fulfill({ json: gj });
  });

  await page.goto('/?source=live');
  await expect(page.getByRole('link', { name: 'Open saved cases' })).toHaveAttribute('href', '?source=saved');
  await expect(page.locator('.trend-status')).toContainText('No trend map for temperature of the planet or a continent (whole year).');
  assert.equal(gridRequests.some(u => u.includes('global_temp')), false);

  // The whole planet has no map and no place to mark: only the claim and its verdict are on the stage.
  await expect(page.locator('.stage-title .big')).toHaveText(stopped.case.claim_text);
  await expect(page.getByTestId('stage-verdict')).toContainText('Refuted');
  await expect(page.getByTestId('trend-legend')).toHaveCount(0);
  await expect(page.getByTestId('mark-legend')).toHaveCount(0);

  // A case in the US: the Ukraine map must not stay on the globe; the case's own result is drawn at its place.
  await page.locator('[data-case="newyork-winter-warming"]').click();
  await expect(page.locator('.stage-title .big')).toHaveText(ny.case.claim_text);
  await expect(page.locator('.stage-title .src')).toHaveText(ny.case.place.name);
  await expect(page.getByTestId('trend-legend')).toHaveCount(0);
  await expect(page.getByTestId('timeline')).toHaveCount(0);
  await expect(page.locator('.trend-caption')).toHaveCount(0);
  await expect(page.getByTestId('mark-legend')).toContainText(`This case at ${ny.case.place.name}`);
  const verdict = page.getByTestId('stage-verdict');
  await expect(verdict).toContainText({ confirmed: 'Confirmed', refuted: 'Refuted', not_proven: 'Not proven' }[ny.verdict]);
  // White when the trend could be chance, the variable's colour when it is clear.
  if (ny.verdict === 'not_proven') await expect(verdict).toHaveAttribute('data-mark', 'rgb(244,244,240)');
  else await expect(verdict).not.toHaveAttribute('data-mark', 'rgb(244,244,240)');
  await expect(page.locator('.trend-status')).toContainText('The trend map covers Ukraine and its neighbours.');

  // A layer picked by hand is shown again, and says it is not about the open case.
  await page.getByRole('group', { name: 'Trend map season' }).getByRole('button', { name: 'Winter' }).click();
  await expect(page.getByTestId('trend-legend')).toBeVisible();
  await expect(page.locator('.stage-title .big')).toHaveText('Where is air temperature changing over Ukraine?');
  await expect(page.locator('.stage-title .src')).toHaveText('The map you picked; it is not about the open case');
  await expect(page.getByTestId('stage-verdict')).toHaveCount(0);
  assert.deepEqual(errors, []);
});

test('year bounds clamp on variable change, global_temp swaps to region select, and claim editing restores Read claim', async ({ page }) => {
  const errors = [];
  const placeUrls = [];
  page.on('pageerror', e => errors.push(e.stack || e.message));
  await page.route('https://gibs.earthdata.nasa.gov/**', route => route.abort());
  await page.route('**/api/cases', route => route.fulfill({ json: [] }));
  await page.route('**/api/variables', route => route.fulfill({ json: VARIABLES }));
  await page.route('**/api/regions', route => route.fulfill({ json: REGIONS }));
  await page.route('**/api/places?*', route => {
    placeUrls.push(route.request().url());
    return route.fulfill({ json: [heat.case.place] });
  });

  await page.goto('/?source=live');
  await page.locator('.case-parameters').evaluate(el => { el.open = true; });
  const variable = page.getByRole('combobox', { name: 'Variable', exact: true });
  await expect(variable).toBeEnabled();
  const from = page.getByLabel('From', { exact: true });
  const to = page.getByLabel('To', { exact: true });
  await expect(from).toHaveAttribute('min', '1981');
  await expect(to).toHaveAttribute('max', '2025');
  await expect(page.locator('.case-parameters fieldset')).toContainText('1981–2025 · at least 15 years.');

  await variable.selectOption('global_temp');
  await expect(page.getByRole('combobox', { name: 'Region', exact: true })).toHaveValue('region:globe');
  await expect(page.getByLabel('Place', { exact: true })).toHaveCount(0);
  await expect(from).toHaveAttribute('min', '1850');
  await expect(to).toHaveAttribute('max', '2025');
  await from.fill('1880');
  await to.fill('2025');
  await page.getByRole('combobox', { name: 'Region', exact: true }).selectOption('region:europe');

  await variable.selectOption('precip_gpm');
  await expect(from).toHaveValue('1998');
  await expect(to).toHaveValue('2024');
  await expect(from).toHaveAttribute('min', '1998');
  await expect(to).toHaveAttribute('max', '2024');
  await expect(page.getByLabel('Place', { exact: true })).toHaveValue('');

  await page.getByLabel('Place', { exact: true }).fill('Ky');
  await page.getByRole('button', { name: heat.case.place.name, exact: true }).click();
  assert.ok(placeUrls.some(u => u.includes('include_regions=false')), placeUrls.join(', '));
  await expect(page.getByRole('button', { name: /Check claim/ })).toBeVisible();

  await page.getByLabel('Claim', { exact: true }).fill('A freshly edited claim text');
  await expect(page.getByRole('button', { name: /Read claim/ })).toBeVisible();
  assert.deepEqual(errors, []);
});

test('source table labels reflect CAG/Giovanni and Giovanni timeseries links point to public Giovanni page', async ({ page }) => {
  const errors = [];
  page.on('pageerror', e => errors.push(e.stack || e.message));
  await page.route('https://gibs.earthdata.nasa.gov/**', route => route.abort());

  await page.goto('/?source=saved#case=global-warming-stopped');
  await page.locator('.chart-values > summary').click();
  await expect(page.locator('.chart-table thead a').first()).toContainText('NOAA Climate at a Glance');

  await page.goto('/?source=saved#case=kyiv-summer-rain-gpm');
  await page.locator('.chart-values > summary').click();
  const gpmHeaderLink = page.locator('.chart-table thead a').first();
  await expect(gpmHeaderLink).toContainText('NASA Giovanni');
  await expect(gpmHeaderLink).toHaveAttribute('href', 'https://giovanni.gsfc.nasa.gov/giovanni/');
  await page.locator('.sources > summary').click();
  const giovanniCaseLink = page.getByRole('link', { name: /Giovanni \(sign-in needed for the raw request\)/ });
  await expect(giovanniCaseLink).toHaveAttribute('href', 'https://giovanni.gsfc.nasa.gov/giovanni/');

  await page.goto('/?source=saved');
  await page.getByRole('tab', { name: 'Pollution events' }).click();
  await page.locator('.ev-card .technical > summary').click();
  const giovanniEvLink = page.getByRole('link', { name: /Giovanni \(sign-in needed for the raw request\)/ });
  await expect(giovanniEvLink).toHaveAttribute('href', 'https://giovanni.gsfc.nasa.gov/giovanni/');
  assert.deepEqual(errors, []);
});

test('Use map centre is available in live mode and Globe view flies back to planet view', async ({ page }) => {
  const errors = [];
  page.on('pageerror', e => errors.push(e.stack || e.message));
  await page.route('https://gibs.earthdata.nasa.gov/**', route => route.abort());
  await page.route('**/api/cases', route => route.fulfill({ json: [] }));
  await page.route('**/api/variables', route => route.fulfill({ json: VARIABLES }));
  await page.route('**/api/grid/index', route => route.fulfill({ json: [] }));

  await page.goto('/?source=live');
  await page.locator('.globe[data-state="ready"]').waitFor();
  await expect(page.getByRole('button', { name: 'Use map centre' })).toBeVisible();
  await page.getByRole('button', { name: 'Globe view' }).click();
  await expect(page.locator('.globe-proj')).toHaveText('3D globe');
  assert.deepEqual(errors, []);
});

test('events workspace filters window radios from valid_windows, clamps when switching compounds and shows geocoder errors', async ({ page }) => {
  const errors = [];
  let eventPosts = 0;
  page.on('pageerror', e => errors.push(e.stack || e.message));
  await page.route('https://gibs.earthdata.nasa.gov/**', route => route.abort());

  const no2 = { ...laNo2.compound, valid_windows: [1, 2, 3] };
  const aod = {
    ...no2,
    id: 'aod',
    label: 'Aerosol optical depth',
    first_year: 2000,
    last_year: 2025,
    event_bounds: [
      { window_years: 1, earliest: '2001-01', latest: '2025-01' },
      { window_years: 2, earliest: '2002-01', latest: '2024-01' },
      { window_years: 3, earliest: '2003-01', latest: '2023-01' },
      { window_years: 4, earliest: '2004-01', latest: '2022-01' },
      { window_years: 5, earliest: '2005-01', latest: '2021-01' },
    ],
    valid_windows: [1, 2, 3, 4],
  };
  const profile = {
    spec: { compound_id: 'no2', place: evSites[3].place, window_years: 1, use_control: true },
    compound: no2,
    site: laNo2.site,
    control: laNo2.control,
    earliest: '2006-01',
    latest: '2025-01',
    points: [],
    provenance: laNo2.provenance,
    meta: laNo2.meta,
  };

  await page.route('**/api/event-sites', route => route.fulfill({ json: [evSites[3]] }));
  await page.route('**/api/compounds', route => route.fulfill({ json: [no2, aod] }));
  await page.route('**/api/events/*', route => route.fulfill({ json: laNo2 }));
  await page.route('**/api/event/profile', route => route.fulfill({ json: profile }));
  await page.route('**/api/event', route => { eventPosts++; return route.fulfill({ json: laNo2 }); });
  await page.route('**/api/places?*', route => route.fulfill({ status: 503, json: { error: { code: 'source_unavailable', message: 'Geocoder offline' } } }));

  await page.goto('/?source=live&mode=events');
  const radios = page.getByRole('radiogroup').getByRole('radio');
  await expect(radios).toHaveText(['1', '2', '3']);

  await page.getByLabel('What to measure').selectOption('aod');
  await expect(radios).toHaveText(['1', '2', '3', '4']);
  await radios.filter({ hasText: '4' }).click();
  await expect(radios.filter({ hasText: '4' })).toHaveAttribute('aria-checked', 'true');

  // Switch back to no2: window_years clamps into [1, 2, 3] and picks 3.
  await page.getByLabel('What to measure').selectOption('no2');
  await expect(radios).toHaveText(['1', '2', '3']);
  await expect(radios.filter({ hasText: '3' })).toHaveAttribute('aria-checked', 'true');

  // Pending slider debounce is cancelled if a preset is chosen before it fires.
  const beforePosts = eventPosts;
  await page.locator('.ev-range').fill(String(Number(await page.locator('.ev-range').getAttribute('min')) + 1));
  await page.locator('[data-event="la-no2-lockdown"]').click();
  await page.waitForTimeout(600);
  assert.equal(eventPosts, beforePosts);

  await page.getByLabel('Place', { exact: true }).fill('Berlin');
  await expect(page.getByRole('alert')).toContainText('Place search failed: Geocoder offline');
  assert.deepEqual(errors, []);
});

test('in the events mode a click on the globe moves the event to that spot', async ({ page }) => {
  const errors = [], posted = [];
  page.on('pageerror', e => errors.push(e.stack || e.message));
  await page.route('https://gibs.earthdata.nasa.gov/**', route => route.abort());
  const profile = { spec: { compound_id: laNo2.compound.id, place: evSites[3].place, window_years: 1, use_control: true }, compound: laNo2.compound,
    site: laNo2.site, control: laNo2.control, earliest: '2006-01', latest: '2025-01', points: [], provenance: laNo2.provenance, meta: laNo2.meta };
  await page.route('**/api/cases', route => route.fulfill({ json: [] }));
  await page.route('**/api/event-sites', route => route.fulfill({ json: [evSites[3]] }));
  await page.route('**/api/compounds', route => route.fulfill({ json: [laNo2.compound] }));
  await page.route('**/api/events/*', route => route.fulfill({ json: laNo2 }));
  await page.route('**/api/event/profile', route => route.fulfill({ json: profile }));
  await page.route('**/api/event', route => { posted.push(route.request().postDataJSON()); return route.fulfill({ json: laNo2 }); });

  await page.goto('/?source=live&mode=events');
  await expect(page.locator('.stage-title .big')).toHaveText(evSites[3].label);
  await expect(page.locator('.globe-hint')).toHaveText('Click the map to move the event there', { timeout: 20_000 });
  await expect(page.locator('.globe')).not.toHaveAttribute('data-flight', 'true', { timeout: 15_000 });
  const box = await page.locator('.globe-map canvas').boundingBox();
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await expect.poll(() => posted.length).toBe(1);
  assert.match(posted[0].place.place_id, /^pt:-?\d+\.\d\d,-?\d+\.\d\d$/);
  assert.equal(posted[0].compound_id, laNo2.compound.id);
  await expect(page.getByLabel('Place', { exact: true })).toHaveValue(posted[0].place.name);
  await expect(page.locator('.panel [data-event][aria-pressed="true"]')).toHaveCount(0);
  assert.deepEqual(errors, []);
});
