import { test, expect } from '@playwright/test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const load = async id => JSON.parse(await readFile(new URL(`../../data/cases/${id}.json`, import.meta.url), 'utf8'));
const heat = await load('kyiv-summer-heat');
const rain = await load('kyiv-summer-rain');
const codes = { ssp126: 'SSP1-2.6', ssp245: 'SSP2-4.5', ssp585: 'SSP5-8.5' };
const ordinal = n => `${n}${n % 100 >= 11 && n % 100 <= 13 ? 'th' : { 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] ?? 'th'}`;

test.beforeEach(async ({ page }) => {
  await page.route('https://gibs.earthdata.nasa.gov/**', route => route.abort());
  // Live mode lists /api/cases; an empty list keeps these tests on the form path.
  await page.route('**/api/cases', route => route.fulfill({ json: [] }));
});

async function saved(page, id, viewport = { width: 1440, height: 1100 }) {
  await page.setViewportSize(viewport);
  await page.goto('/');
  await page.locator(`[data-case="${id}"]`).click();
  await page.getByTestId('record-chart').scrollIntoViewIfNeeded();
}

async function live(page, result) {
  await page.route('**/api/variables', route => route.fulfill({ json: [result.variable] }));
  await page.route('**/api/places?*', route => route.fulfill({ json: [result.case.place] }));
  await page.route('**/api/check', route => route.fulfill({ json: result }));
  await page.goto('/?source=live');
  await expect(page.getByRole('combobox', { name: 'Variable', exact: true })).toBeEnabled();
  await page.getByLabel('Claim', { exact: true }).fill('Test-only intercepted case');
  await page.getByLabel('Place', { exact: true }).fill(result.case.place.name.slice(0, 2));
  await page.getByRole('button', { name: result.case.place.name, exact: true }).click();
  await page.getByRole('button', { name: 'Check claim', exact: true }).click();
  await page.getByTestId('record-chart').scrollIntoViewIfNeeded();
}

const panel = page => page.getByTestId('scenarios');
const pathButton = (page, path) => panel(page).getByRole('group', { name: 'Emissions path' }).getByRole('button', { name: new RegExp(path.label) });
const nodeButton = (page, year) => panel(page).getByRole('group', { name: 'Scenario year' }).getByRole('button', { name: String(year), exact: true });

test('three plain-named paths with codes; medians at node years and the selected fan from JSON', async ({ page }) => {
  await saved(page, 'kyiv-summer-heat');
  const layer = page.getByTestId('scenarios-layer');
  for (const path of heat.scenarios.paths) {
    await expect(pathButton(page, path)).toContainText(codes[path.id]);
    const dots = layer.locator(`.scenario[data-path="${path.id}"] circle`);
    assert.deepEqual(await dots.evaluateAll(nodes => nodes.map(node => [Number(node.dataset.year), Number(node.dataset.value)])), path.years.map((year, i) => [year, path.median_value[i]]));
  }
  // Default: "Roughly as now" at 2050.
  const as = heat.scenarios.paths.find(p => p.id === 'ssp245');
  await expect(pathButton(page, as)).toHaveAttribute('aria-pressed', 'true');
  await expect(nodeButton(page, 2050)).toHaveAttribute('aria-pressed', 'true');
  await expect(layer.getByTestId('scenario-fan')).toHaveAttribute('data-path', 'ssp245');
  const i = as.years.indexOf(2050);
  await expect(panel(page).getByTestId('scenario-window')).toHaveText(`2050 = average of ${as.windows[i].replace('-', '–')}`);
  await expect(panel(page).getByTestId('scenario-readout')).toContainText(`median ${as.median_value[i]} °C, models ${as.low_value[i]} to ${as.high_value[i]} °C`);

  const fast = heat.scenarios.paths.find(p => p.id === 'ssp126');
  await pathButton(page, fast).click();
  await expect(layer.getByTestId('scenario-fan')).toHaveAttribute('data-path', 'ssp126');
  await nodeButton(page, 2100).click();
  const j = fast.years.indexOf(2100);
  await expect(panel(page).getByTestId('scenario-window')).toHaveText(`2100 = average of ${fast.windows[j].replace('-', '–')}`);
  await expect(panel(page).getByTestId('scenario-readout')).toContainText(`median ${fast.median_value[j]} °C`);
});

test('the analog sentence comes from analogs[i], including the beyond-record case', async ({ page }) => {
  await saved(page, 'kyiv-summer-heat');
  const as = heat.scenarios.paths.find(p => p.id === 'ssp245');
  const a = as.analogs[as.years.indexOf(2050)];
  assert.equal(a.beyond_record, false);
  const rank = a.analog_rank === 1 ? 'warmest' : `${ordinal(a.analog_rank)} warmest`;
  await expect(panel(page).getByTestId('scenario-analog')).toHaveText(`A typical summer around 2050 would be like ${a.analog_year} (${a.analog_value} °C), the ${rank} on record.`);

  const hot = heat.scenarios.paths.find(p => p.id === 'ssp585');
  const beyond = hot.analogs.find(item => item.beyond_record);
  assert.ok(beyond, 'the saved case has a beyond-record node');
  await pathButton(page, hot).click();
  await nodeButton(page, beyond.year).click();
  await expect(panel(page).getByTestId('scenario-analog')).toHaveText(`A typical summer around ${beyond.year} would be beyond anything in the ${heat.case.start_year}–${heat.case.end_year} record.`);
});

test('a precipitation case words the analog as wettest', async ({ page }) => {
  await live(page, rain);
  const as = rain.scenarios.paths.find(p => p.id === 'ssp245');
  const a = as.analogs[as.years.indexOf(2050)];
  await expect(panel(page).getByTestId('scenario-analog')).toHaveText(`A typical summer around 2050 would be like ${a.analog_year} (${a.analog_value} ${rain.variable.units}), the ${ordinal(a.analog_rank)} wettest on record.`);
});

test('disclaimer, source and baseline period; choosing a path never changes the verdict', async ({ page }) => {
  await saved(page, 'kyiv-summer-heat');
  await expect(panel(page)).toContainText('Climate-model scenarios, not a weather forecast. Choosing a scenario does not change the verdict about the past.');
  await expect(panel(page)).toContainText(`Source: ${heat.scenarios.source}.`);
  await expect(panel(page)).toContainText(`Scenario baseline: ${heat.scenarios.baseline_period} average, ${heat.scenarios.baseline_value} °C.`);
  const verdict = await page.locator('.verdict').innerText();
  const metric = await page.locator('.metric-value').innerText();
  for (const path of heat.scenarios.paths) await pathButton(page, path).click();
  await nodeButton(page, 2100).click();
  assert.equal(await page.locator('.verdict').innerText(), verdict);
  assert.equal(await page.locator('.metric-value').innerText(), metric);
});

test('hovering a node right of "now" shows that node from the selected path', async ({ page }) => {
  await saved(page, 'kyiv-summer-heat');
  const as = heat.scenarios.paths.find(p => p.id === 'ssp245');
  const dot = page.getByTestId('scenarios-layer').locator('.scenario[data-path="ssp245"] circle[data-year="2070"]');
  const box = await dot.boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  const i = as.years.indexOf(2070);
  const tip = await page.getByTestId('chart-tooltip').innerText();
  assert.match(tip, new RegExp(`^${as.label} · 2070`));
  assert.match(tip, new RegExp(`Median\\s+${as.median_value[i]} °C`));
  assert.match(tip, new RegExp(`Models\\s+${as.low_value[i]} to ${as.high_value[i]} °C`));
});

test('without scenarios the future zone is hidden and one line says why', async ({ page }) => {
  await saved(page, 'lviv-drier');
  await expect(page.getByTestId('scenarios-layer')).toHaveCount(0);
  await expect(page.getByTestId('scenarios')).toHaveCount(0);
  await expect(page.getByTestId('scenarios-none')).toHaveText('No future scenarios here: there is no CMIP6 tile near this place.');
  await saved(page, 'kyiv-winter-snow');
  await expect(page.getByTestId('scenarios-none')).toHaveText('No future scenarios here: CMIP6 covers only air temperature and precipitation for the year, summer and winter.');
});

test('scenarios fit desktop and phone widths; screenshots', async ({ page }) => {
  for (const [name, viewport] of [['desktop', { width: 1440, height: 1100 }], ['mobile', { width: 390, height: 844 }]]) {
    await saved(page, 'kyiv-summer-heat', viewport);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, name);
    const box = await page.getByTestId('record-chart').boundingBox();
    assert.ok(box.x >= 0 && box.x + box.width <= viewport.width, name);
    await page.getByTestId('record-chart').screenshot({ path: `test-results/scenarios-${name}.png` });
  }
});
