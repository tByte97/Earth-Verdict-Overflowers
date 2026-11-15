import { test, expect } from '@playwright/test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const load = async id => JSON.parse(await readFile(new URL(`../../data/cases/${id}.json`, import.meta.url), 'utf8'));
const heat = await load('kyiv-summer-heat');
const dry = await load('lviv-drier');
const flat = await load('global-warming-stopped');

test.beforeEach(async ({ page }) => {
  await page.route('https://gibs.earthdata.nasa.gov/**', route => route.abort());
});

async function saved(page, id, viewport = { width: 1440, height: 1100 }) {
  await page.setViewportSize(viewport);
  await page.goto('/');
  await page.getByLabel('Saved case').selectOption(id);
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

// The pointer position of a year, from the same linear scale the chart uses (left/right padding 44/12).
async function hoverYear(page, result, year) {
  const svg = page.getByTestId('record-chart').locator('svg').first();
  const box = await svg.boundingBox();
  const width = Number((await svg.getAttribute('viewBox')).split(' ')[2]);
  // With scenarios the axis runs on to their last node year.
  const first = result.series[0].year;
  const end = Math.max(result.series.at(-1).year, ...(result.scenarios?.paths.flatMap(path => path.years) ?? []));
  const x = 44 + (year - first) / (end - first) * (width - 56);
  await page.mouse.move(box.x + x * box.width / width, box.y + box.height / 3);
  return page.getByTestId('chart-tooltip').innerText();
}

const runs = d => (d.match(/M/g) ?? []).length;

test('station gaps stay gaps: the line breaks, no dot, no zero, and the table says so', async ({ page }) => {
  await saved(page, 'kyiv-summer-heat');
  const chart = page.getByTestId('record-chart');
  const gaps = heat.witness.series.filter(point => point.value === null).map(point => point.year);
  assert.deepEqual(gaps, [2007, 2008, 2009, 2025]);
  // 1981–2006 and 2010–2024: two separate runs, never bridged across 2007–2009.
  assert.equal(runs(await chart.getByTestId('station-line').getAttribute('d')), 2);
  assert.equal(await chart.locator('.station-dot').count(), heat.witness.series.length - gaps.length);
  assert.equal(runs(await chart.getByTestId('series-line').getAttribute('d')), 1);
  const tip = await hoverYear(page, heat, 2008);
  assert.match(tip, /Station\s+no measurement/);
  assert.doesNotMatch(tip, /Station\s+0 /);
  assert.match(await hoverYear(page, heat, 2006), /Station\s+18\.74 °C/);
  await chart.locator('.chart-values > summary').click();
  const row = await chart.locator('.chart-values tbody tr').filter({ hasText: /^2008/ }).innerText();
  assert.match(row, /no station measurement/);
});

test('a missing reanalysis year breaks the series line and gets no stripe', async ({ page }) => {
  // Test-only variant with one null year; never shared case data.
  const result = structuredClone(heat);
  result.series.find(point => point.year === 2000).value = null;
  // The prefix counts would no longer match the series, so this variant omits the optional history.
  delete result.detection_history;
  await live(page, result);
  const chart = page.getByTestId('record-chart');
  assert.equal(runs(await chart.getByTestId('series-line').getAttribute('d')), 2);
  await expect(chart.locator('.series-dot[data-year="2000"]')).toHaveCount(0);
  await expect(chart.locator('.stripe[data-year="2000"]')).toHaveCount(0);
  assert.match(await hoverYear(page, result, 2000), /Value\s+no data/);
});

test('year stripes: one per observed year, coloured around baseline.mean, with the baseline drawn and named', async ({ page }) => {
  await saved(page, 'kyiv-summer-heat');
  const chart = page.getByTestId('record-chart');
  const stripes = chart.locator('.stripe');
  await expect(stripes).toHaveCount(heat.series.length);
  assert.deepEqual(await stripes.evaluateAll(nodes => nodes.map(node => Number(node.dataset.value))), heat.series.map(point => point.value));
  // Above-average years take the warm end, below-average years the cool end.
  const fill = year => chart.locator(`.stripe[data-year="${year}"]`).getAttribute('fill');
  const rgb = async year => (await fill(year)).match(/\d+/g).map(Number);
  const hot = heat.series.reduce((a, b) => b.value > a.value ? b : a), cold = heat.series.reduce((a, b) => b.value < a.value ? b : a);
  const [hr, , hb] = await rgb(hot.year), [cr, , cb] = await rgb(cold.year);
  assert.ok(hr > hb && cb > cr, `warm ${hot.year} / cool ${cold.year}`);
  await expect(chart.getByTestId('baseline')).toHaveAttribute('data-value', String(heat.baseline.mean));
  await expect(chart.locator('.baseline-label')).toHaveText(`${heat.baseline.period} average`);
  await expect(chart.locator('.record-legend')).toContainText(`${heat.baseline.period} average, ${heat.baseline.mean} °C`);
  await expect(chart.locator('.record-legend')).toContainText('Summer average, °C');
  await expect(chart.locator('.record-legend')).toContainText('station Kyiv');
  await expect(chart.locator('.record-note')).toContainText(`the ${heat.baseline.period} normal`);
});

test('a record without a 1991–2020 normal names the whole-record average', async ({ page }) => {
  assert.equal(flat.baseline.kind, 'series_mean');
  await live(page, flat);
  const chart = page.getByTestId('record-chart');
  await expect(chart.locator('.record-note')).toContainText(`whole-record average (${flat.baseline.period}`);
  await expect(chart.locator('.record-legend')).toContainText('No ground station for this place');
  await expect(chart.getByTestId('station-line')).toHaveCount(0);
});

test('hover tooltip shows year, value and the trend-line value from sen.band', async ({ page }) => {
  await saved(page, 'kyiv-summer-heat');
  const point = heat.series.find(p => p.year === 1995);
  const mid = heat.sen.band.find(p => p.year === 1995).mid;
  const station = heat.witness.series.find(p => p.year === 1995).value;
  const tip = await hoverYear(page, heat, 1995);
  assert.match(tip, /^Summer 1995/);
  assert.match(tip, new RegExp(`Value\\s+${point.value} °C`));
  assert.match(tip, new RegExp(`Trend line\\s+${mid} °C`));
  assert.match(tip, new RegExp(`Station\\s+${station} °C`));
  await page.mouse.move(0, 0);
  await expect(page.getByTestId('chart-tooltip')).toHaveCount(0);
  // Keyboard: arrow keys walk the years.
  await page.getByTestId('record-chart').locator('svg').first().focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByTestId('chart-tooltip')).toContainText(`Summer ${heat.series[0].year}`);
});

test('a case without a station draws no station line', async ({ page }) => {
  await saved(page, 'lviv-drier');
  const chart = page.getByTestId('record-chart');
  await expect(chart.getByTestId('station-line')).toHaveCount(0);
  assert.doesNotMatch(await hoverYear(page, dry, 2000), /Station/);
});

test('emergence: the saved case marks emerged_year; a null emerged_year shows "—" and no marker', async ({ page }) => {
  const emerged = heat.detection_history.emerged_year;
  assert.equal(typeof emerged, 'number');
  await saved(page, 'kyiv-summer-heat');
  await expect(page.getByTestId('emerged-marker')).toContainText(`emerged ${emerged}`);
  await page.locator('.detection-simulator > summary').click();
  await expect(page.getByTestId('emerged-year')).toHaveText(String(emerged));
  await expect(page.locator('.history-timeline')).toContainText(`From ${emerged} on the rise stays significant`);
  const blocks = page.locator('.history-timeline rect');
  await expect(blocks).toHaveCount(heat.detection_history.points.length);
  const significant = heat.detection_history.points.map(p => p.status === 'ok' && p.p < heat.detection_history.alpha);
  assert.deepEqual(await blocks.evaluateAll(nodes => nodes.map(node => node.dataset.significant === 'true')), significant);

  // Test-only variant: the backend says the signal never emerged.
  const result = structuredClone(heat);
  result.detection_history.emerged_year = null;
  await live(page, result);
  await expect(page.getByTestId('emerged-marker')).toHaveCount(0);
  await page.locator('.detection-simulator > summary').click();
  await expect(page.getByTestId('emerged-year')).toHaveText('—');
  await expect(page.locator('.history-timeline')).toContainText('The signal has not yet clearly left the noise.');
});

test('the chart fits desktop and phone widths; screenshots', async ({ page }) => {
  for (const [name, viewport] of [['desktop', { width: 1440, height: 1100 }], ['mobile', { width: 390, height: 844 }]]) {
    await saved(page, 'kyiv-summer-heat', viewport);
    const box = await page.getByTestId('record-chart').boundingBox();
    assert.ok(box.x >= 0 && box.x + box.width <= viewport.width, name);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, name);
    await hoverYear(page, heat, 2010);
    await page.getByTestId('record-chart').screenshot({ path: `test-results/record-chart-${name}.png` });
  }
});
