import { test, expect } from '@playwright/test';
import assert from 'node:assert/strict';
import { readFile, mkdir } from 'node:fs/promises';

const read = async path => JSON.parse(await readFile(new URL(path, import.meta.url), 'utf8'));
const heat = await read('../../data/cases/kyiv-summer-heat.json');
const rain = await read('../../data/cases/lviv-drier.json');
const params = { air_temp: 'T2M', precip: 'PRECTOTCORR' };
const layers = {};
for (const [variable, param] of Object.entries(params)) for (const season of ['JJA', 'year', 'DJF']) layers[`${variable}/${season}`] = await read(`../../data/layers/trends_${param}_${season}.geojson`);
const baseURL = process.env.TEST_BASE_URL || 'http://127.0.0.1:4173';
let browser;
test.beforeAll(async ({ browser: sharedBrowser }) => { browser = sharedBrowser; });

// The mocked backend adds the cell counts the real one sends with each layer.
// Halo cells (fetched around Ukraine so the map fades out over real data) are never counted.
const tested = layer => layer.features.filter(f => !f.properties.halo);
const withCounts = layer => ({ ...layer, n_cells: tested(layer).length, n_significant_fdr: tested(layer).filter(f => f.properties.significant_fdr).length, n_significant_raw: 0 });
// Counts come with the saved layer files now; a mocked old backend sends none.
const withoutCounts = ({ n_cells, n_significant_fdr, n_significant_raw, stats_engine, ...rest }) => rest;
// With one common test for all cells the saved precipitation layers hold no pair of opposite significant cells,
// so the pair callout is exercised with a fixed pair, as the layer file carries it when there is one.
const fixturePair = { a: { lat: 50, lon: 40, slope_per_decade: 3.9633, p: 0.00024 }, b: { lat: 46.5, lon: 40, slope_per_decade: -12.0948, p: 0 }, distance_km: 389, significance: 'fdr' };
const entry = ({ variable_id, season, start_year, end_year, units_per_decade }) => ({ variable_id, season, start_year, end_year, units_per_decade });

async function open({ live = false, index = true, counts = true, pair = false, imagery = false, viewport = { width: 1440, height: 1000 }, hash = '' } = {}) {
  const page = await browser.newPage({ viewport, reducedMotion: 'reduce' });
  // Assertions run offline; review screenshots load the imagery.
  if (!imagery) await page.route('https://gibs.earthdata.nasa.gov/**', route => route.abort());
  const errors = [];
  const checks = [];
  page.on('pageerror', error => errors.push(error.stack || error.message));
  if (live) {
    // Live mode lists /api/cases; an empty list keeps these tests on the form path.
    await page.route('**/api/cases', route => route.fulfill({ json: [] }));
    await page.route('**/api/variables', route => route.fulfill({ json: [heat.variable, rain.variable] }));
    await page.route('**/api/grid/index', route => (index ? route.fulfill({ json: Object.values(layers).map(entry) }) : route.fulfill({ status: 404, json: { detail: 'Not Found' } })));
    await page.route('**/api/grid?*', route => {
      const url = new URL(route.request().url());
      const key = `${url.searchParams.get('variable_id')}/${url.searchParams.get('season')}`;
      const layer = pair && key === 'precip/JJA' ? { ...layers[key], pair: fixturePair } : layers[key];
      return route.fulfill({ json: counts ? withCounts(layer) : withoutCounts(layer) });
    });
    await page.route('**/api/places?*', route => route.fulfill({ json: [heat.case.place] }));
    await page.route('**/api/check', route => { checks.push(route.request().postDataJSON()); return route.fulfill({ json: heat }); });
  }
  await page.goto(baseURL + (live ? '/?source=live' : '/') + hash);
  await expect(page.locator('.globe-map canvas')).toBeVisible({ timeout: 20_000 });
  return { page, errors, checks };
}

// Same display scale as the app: the 95th percentile of |slope|, rounded up to a nice step.
function niceLimit(layer) {
  const sorted = tested(layer).map(f => Math.abs(f.properties.slope_per_decade)).sort((a, b) => a - b);
  const x = sorted[Math.floor(0.95 * (sorted.length - 1))], e = 10 ** Math.floor(Math.log10(x)), f = x / e;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * e;
}

const mapCentre = async page => {
  const box = await page.locator('.globe-map').boundingBox();
  return [box.x + box.width / 2, box.y + box.height / 2];
};

test('the layer legend and caption repeat the values sent by the API', async () => {
  const { page, errors } = await open({ live: true });
  try {
    const layer = withCounts(layers['air_temp/JJA']);
    const legend = page.getByTestId('trend-legend');
    await expect(legend).toContainText(`Summer air temperature trend, ${layer.units_per_decade}`);
    const lim = Number(niceLimit(layer).toPrecision(2));
    await expect(legend.locator('.trend-legend-ends')).toHaveText(`−${lim}0+${lim}`);
    await expect(legend).toContainText(`dots = significant after FDR (q = ${layer.q})`);
    await expect(legend).toContainText('cooler ◂ ▸ warmer');
    await expect(page.locator('.trend-caption')).toHaveText(`${Math.round(layer.n_significant_fdr / layer.n_cells * 100)}% of cells over Ukraine show a significant trend after FDR · chance alone would give ~5%`);
    const fade = page.getByLabel('Fade trends that could be chance');
    await expect(fade).toBeDisabled();
    await expect(page.locator('#fade-reason')).toHaveText('Every cell is significant after FDR.');
    await page.getByRole('group', { name: 'Trend map season' }).getByRole('button', { name: 'Winter' }).click();
    await expect(fade).toBeEnabled();
    await fade.uncheck();
    await expect(page.getByTestId('trend-legend')).not.toContainText('faded = could be chance');
    await page.getByRole('group', { name: 'Trend map variable' }).getByRole('button', { name: 'Precipitation' }).click();
    await page.getByRole('group', { name: 'Trend map season' }).getByRole('button', { name: 'Year' }).click();
    await expect(fade).toBeDisabled();
    await expect(page.locator('#fade-reason')).toHaveText('No cells are significant after FDR.');
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('hovering a cell shows its exact values from the layer', async () => {
  const { page, errors } = await open();
  try {
    // Reduced motion: choosing a case jumps to its local view. Hover beside the station marker.
    await page.locator('[data-case="lviv-drier"]').click();
    await expect(page.getByTestId('trend-legend')).toContainText('Year precipitation trend');
    const [x, y] = await mapCentre(page);
    await page.mouse.move(x + 70, y - 10);
    await page.mouse.move(x + 80, y);
    const tip = page.getByRole('tooltip');
    await expect(tip).toContainText('click to investigate');
    // The tip names its cell; every value in it must be that cell's value in the layer.
    const [, lat, ns, lon, ew] = (await tip.locator('.trend-tip-title').innerText()).match(/([\d.]+)° ([NS]), ([\d.]+)° ([EW])/);
    const cell = layers['precip/year'].features.map(f => f.properties)
      .find(c => c.lat === Number(lat) * (ns === 'N' ? 1 : -1) && c.lon === Number(lon) * (ew === 'E' ? 1 : -1));
    assert.ok(cell, 'the tooltip cell exists in the layer');
    const sign = cell.slope_per_decade > 0 ? '+' : '−';
    await expect(tip).toContainText(`Trend ${sign}${Math.abs(cell.slope_per_decade)} mm/decade`);
    await expect(tip).toContainText(`p ${cell.p < 0.001 ? '<0.001' : cell.p}`);
    await expect(tip).toContainText(`${cell.significant_fdr ? 'significant' : 'could be chance'}${cell.halo ? ' · outside the Ukraine area' : ''} · click to investigate`);
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('precipitation layers show the opposite pair; temperature layers say there is none', async () => {
  const { page, errors } = await open({ live: true, pair: true });
  try {
    await expect(page.getByTestId('pair-callout')).toContainText('No opposite trends here: every significant cell gets warmer.');
    await expect(page.locator('.lead')).toHaveCount(0);
    await page.getByRole('group', { name: 'Trend map variable' }).getByRole('button', { name: 'Precipitation' }).click();
    const pair = fixturePair;
    await expect(page.locator('.lead')).toHaveText(['▲ wetter', '▼ drier']);
    const callout = page.getByTestId('pair-callout');
    await expect(callout).toContainText(`+${pair.a.slope_per_decade} mm/decade, p <0.001`);
    await expect(callout).toContainText(`−${-pair.b.slope_per_decade} mm/decade, p <0.001`);
    await expect(callout).toContainText(`${pair.distance_km} km apart`);
    await expect(callout).toContainText('significant after FDR');
    await expect(callout).toContainText('Possible common driver');
    await page.getByRole('group', { name: 'Trend map variable' }).getByRole('button', { name: 'Air temperature' }).click();
    await expect(page.locator('.lead')).toHaveCount(0);
    await expect(page.getByTestId('pair-callout')).toContainText('No opposite trends here');
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('a map click checks that spot with the layer variable, season and period', async () => {
  const { page, errors, checks } = await open({ live: true });
  try {
    await page.getByRole('group', { name: 'Trend map season' }).getByRole('button', { name: 'Winter' }).click();
    await expect(page.getByTestId('trend-legend')).toContainText('Winter air temperature trend');
    // The first saved case is open, so its station marker sits in the middle of the map: click beside it.
    const [x, y] = await mapCentre(page);
    await page.mouse.click(x + 80, y);
    await expect.poll(() => checks.length).toBe(1);
    const layer = layers['air_temp/DJF'];
    assert.match(checks[0].place.place_id, /^pt:-?\d+\.\d{2},-?\d+\.\d{2}$/);
    assert.equal(checks[0].claim_direction, 'change');
    assert.deepEqual([checks[0].variable_id, checks[0].season, checks[0].start_year, checks[0].end_year], [layer.variable_id, layer.season, layer.start_year, layer.end_year]);
    assert.equal(checks[0].claim_text, `Is winter air temperature changing at ${checks[0].place.name}?`);
    await expect(page.locator('#result-status')).toHaveText('Result: confirmed.');
    const spotHash = check => `#v=${check.variable_id}&s=${check.season}&p=${check.start_year}-${check.end_year}&pt=${check.place.lon}%2C${check.place.lat}`;
    expect(new URL(page.url()).hash).toBe(spotHash(checks[0]));
    // Changing the layer keeps the picked spot and checks it again.
    await page.getByRole('group', { name: 'Trend map variable' }).getByRole('button', { name: 'Precipitation' }).click();
    await expect.poll(() => checks.length).toBe(2);
    assert.deepEqual([checks[1].place, checks[1].variable_id, checks[1].season], [checks[0].place, 'precip', 'DJF']);
    await expect.poll(() => new URL(page.url()).hash).toBe(spotHash(checks[1]));
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('a picked-spot link restores the spot and checks it in live mode', async () => {
  const { page, errors, checks } = await open({ live: true, hash: '#v=precip&s=DJF&p=1990-2020&pt=30.52,50.45' });
  try {
    await expect.poll(() => checks.length).toBe(1);
    assert.deepEqual([checks[0].variable_id, checks[0].season, checks[0].start_year, checks[0].end_year, checks[0].place.place_id, checks[0].claim_direction], ['precip', 'DJF', 1990, 2020, 'pt:50.45,30.52', 'change']);
    await expect(page.locator('#result-status')).toHaveText('Result: confirmed.');
    await expect(page.locator('.case[aria-pressed="true"]')).toHaveCount(0);
    await expect(page.getByTestId('trend-legend')).toContainText('Winter precipitation trend');
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('a picked-spot link in saved mode shows the spot and says it needs the backend', async () => {
  const { page, errors } = await open({ hash: '#v=precip&s=DJF&p=1981-2025&pt=30.52,50.45' });
  try {
    await expect(page.getByRole('status').filter({ hasText: 'Checking a new spot needs the backend.' })).toBeVisible();
    await expect(page.locator('.hero')).toHaveCount(0);
    await expect(page.locator('.case[aria-pressed="true"]')).toHaveCount(0);
    await expect(page.locator('.stage-title .src')).toHaveText('50.45° N, 30.52° E');
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('without a layer index only the checked case layer is shown, without invented counts', async () => {
  const { page, errors } = await open({ live: true, index: false, counts: false });
  try {
    await expect(page.getByTestId('trend-legend')).toHaveCount(0);
    await expect(page.getByRole('group', { name: 'Trend map variable' })).toHaveCount(0);
    await page.locator('.case-parameters').evaluate(element => { element.open = true; });
    await page.getByLabel('Claim', { exact: true }).fill('Summers in Kyiv are getting hotter');
    await page.getByLabel('Place', { exact: true }).fill('Ky');
    await page.getByRole('button', { name: heat.case.place.name, exact: true }).click();
    await page.getByLabel('Season').selectOption('JJA');
    await page.getByRole('button', { name: /Check claim/ }).click();
    await expect(page.getByTestId('trend-legend')).toContainText('Summer air temperature trend');
    await expect(page.locator('.trend-caption')).toHaveCount(0);
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('saved mode reads the saved layers; map picking is hidden and clicking leaves the case intact', async () => {
  const { page, errors } = await open();
  try {
    await expect(page.getByTestId('trend-legend')).toContainText('Summer air temperature trend');
    await expect(page.getByRole('group', { name: 'Trend map variable' }).getByRole('button')).toHaveText(['Air temperature', 'Precipitation']);
    await expect(page.getByRole('button', { name: 'Use map centre' })).toHaveCount(0);
    await expect(page.locator('.globe-hint')).toHaveCount(0);
    // The saved files carry the cell counts, so the share is printed.
    const saved = layers['air_temp/JJA'];
    await expect(page.locator('.trend-caption')).toHaveText(`${Math.round(saved.n_significant_fdr / saved.n_cells * 100)}% of cells over Ukraine show a significant trend after FDR · chance alone would give ~5%`);
    const [x, y] = await mapCentre(page);
    await page.mouse.click(x + 80, y);
    await expect(page.locator('.trend-note')).toHaveCount(0);
    await expect(page.getByRole('heading', { name: 'Confirmed', exact: true })).toBeVisible();
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('trend map screenshots at 1440 and 390 without horizontal scroll', async () => {
  await mkdir(new URL('../test-results/', import.meta.url), { recursive: true });
  for (const [name, viewport] of [['desktop', { width: 1440, height: 1000 }], ['mobile', { width: 390, height: 844 }]]) {
    const { page, errors } = await open({ imagery: true, viewport });
    try {
      // Reduced motion: switching cases jumps to the Kyiv local view, where the layers lie.
      await page.locator('[data-case="lviv-drier"]').click();
      await page.locator('[data-case="kyiv-summer-heat"]').click();
      await page.getByRole('group', { name: 'Trend map variable' }).getByRole('button', { name: 'Precipitation' }).click();
      await page.getByRole('group', { name: 'Trend map season' }).getByRole('button', { name: 'Summer' }).click();
      // Saved layers hold a pair only when one exists after the common test.
      await expect(page.locator('.lead')).toHaveCount(layers['precip/JJA'].pair ? 2 : 0);
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.waitForTimeout(3000);
      await page.screenshot({ path: `test-results/trend-map-${name}.png`, fullPage: true });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      assert.deepEqual(errors, []);
    } finally { await page.close(); }
  }
});
