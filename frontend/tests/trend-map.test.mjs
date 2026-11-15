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
const withCounts = layer => ({ ...layer, n_cells: layer.features.length, n_significant_fdr: layer.features.filter(f => f.properties.significant_fdr).length, n_significant_raw: 0 });
const entry = ({ variable_id, season, start_year, end_year, units_per_decade }) => ({ variable_id, season, start_year, end_year, units_per_decade });

async function open({ live = false, index = true, counts = true, imagery = false, viewport = { width: 1440, height: 1000 } } = {}) {
  const page = await browser.newPage({ viewport, reducedMotion: 'reduce' });
  // Assertions run offline; review screenshots load the imagery.
  if (!imagery) await page.route('https://gibs.earthdata.nasa.gov/**', route => route.abort());
  const errors = [];
  const checks = [];
  page.on('pageerror', error => errors.push(error.message));
  if (live) {
    await page.route('**/api/variables', route => route.fulfill({ json: [heat.variable, rain.variable] }));
    await page.route('**/api/grid/index', route => (index ? route.fulfill({ json: Object.values(layers).map(entry) }) : route.fulfill({ status: 404, json: { detail: 'Not Found' } })));
    await page.route('**/api/grid?*', route => {
      const url = new URL(route.request().url());
      const layer = layers[`${url.searchParams.get('variable_id')}/${url.searchParams.get('season')}`];
      return route.fulfill({ json: counts ? withCounts(layer) : layer });
    });
    await page.route('**/api/places?*', route => route.fulfill({ json: [heat.case.place] }));
    await page.route('**/api/check', route => { checks.push(route.request().postDataJSON()); return route.fulfill({ json: heat }); });
  }
  await page.goto(baseURL + (live ? '/?source=live' : '/'));
  await expect(page.locator('.globe-map canvas')).toBeVisible({ timeout: 20_000 });
  return { page, errors, checks };
}

// Same display scale as the app: the 95th percentile of |slope|, rounded up to a nice step.
function niceLimit(layer) {
  const sorted = layer.features.map(f => Math.abs(f.properties.slope_per_decade)).sort((a, b) => a - b);
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
    await expect(page.locator('.trend-caption')).toHaveText(`${Math.round(layer.n_significant_fdr / layer.n_cells * 100)}% of cells show a significant trend after FDR · chance alone would give ~5%`);
    await page.getByLabel('Fade trends that could be chance').uncheck();
    await expect(legend).not.toContainText('faded = could be chance');
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('hovering a cell shows its exact values from the layer', async () => {
  const { page, errors } = await open();
  try {
    // Reduced motion: choosing a case jumps to its local view. Hover beside the station marker.
    await page.getByLabel('Saved case').selectOption('lviv-drier');
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
    await expect(tip).toContainText(cell.significant_fdr ? 'significant · click to investigate' : 'could be chance · click to investigate');
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('precipitation layers show the opposite pair; temperature layers say there is none', async () => {
  const { page, errors } = await open({ live: true });
  try {
    await expect(page.getByTestId('pair-callout')).toContainText('No opposite trends here: every significant cell gets warmer.');
    await expect(page.locator('.lead')).toHaveCount(0);
    await page.getByRole('group', { name: 'Trend map variable' }).getByRole('button', { name: 'Precipitation' }).click();
    const { pair } = layers['precip/JJA'];
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
    const [x, y] = await mapCentre(page);
    await page.mouse.click(x, y);
    await expect.poll(() => checks.length).toBe(1);
    const layer = layers['air_temp/DJF'];
    assert.match(checks[0].place.place_id, /^pt:-?\d+\.\d{2},-?\d+\.\d{2}$/);
    assert.equal(checks[0].claim_direction, 'change');
    assert.deepEqual([checks[0].variable_id, checks[0].season, checks[0].start_year, checks[0].end_year], [layer.variable_id, layer.season, layer.start_year, layer.end_year]);
    assert.equal(checks[0].claim_text, `Is winter air temperature changing at ${checks[0].place.name}?`);
    await expect(page.locator('#result-status')).toHaveText('Result: confirmed.');
    // Changing the layer keeps the picked spot and checks it again.
    await page.getByRole('group', { name: 'Trend map variable' }).getByRole('button', { name: 'Precipitation' }).click();
    await expect.poll(() => checks.length).toBe(2);
    assert.deepEqual([checks[1].place, checks[1].variable_id, checks[1].season], [checks[0].place, 'precip', 'DJF']);
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

test('saved mode reads the saved layers; a map click asks for the backend', async () => {
  const { page, errors } = await open();
  try {
    await expect(page.getByTestId('trend-legend')).toContainText('Summer air temperature trend');
    await expect(page.getByRole('group', { name: 'Trend map variable' }).getByRole('button')).toHaveText(['Air temperature', 'Precipitation']);
    // The saved files carry no counts, so there is no share to print.
    await expect(page.locator('.trend-caption')).toHaveCount(0);
    const [x, y] = await mapCentre(page);
    await page.mouse.click(x + 80, y);
    await expect(page.locator('.trend-note')).toContainText('needs the backend');
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
      await page.getByLabel('Saved case').selectOption('lviv-drier');
      await page.getByLabel('Saved case').selectOption('kyiv-summer-heat');
      await page.getByRole('group', { name: 'Trend map variable' }).getByRole('button', { name: 'Precipitation' }).click();
      await page.getByRole('group', { name: 'Trend map season' }).getByRole('button', { name: 'Summer' }).click();
      await expect(page.locator('.lead')).toHaveCount(2);
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.waitForTimeout(3000);
      await page.screenshot({ path: `test-results/trend-map-${name}.png`, fullPage: true });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      assert.deepEqual(errors, []);
    } finally { await page.close(); }
  }
});
