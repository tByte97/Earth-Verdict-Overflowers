import { test } from '@playwright/test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const files = ['kyiv-summer-heat', 'lviv-drier', 'kyiv-winter-snow', 'global-warming-stopped'];
const cases = Object.fromEntries(await Promise.all(files.map(async id => [id, JSON.parse(await readFile(new URL(`../../data/cases/${id}.json`, import.meta.url), 'utf8'))])));
const baseURL = process.env.TEST_BASE_URL || 'http://127.0.0.1:4173';
let browser;
test.beforeAll(async ({ browser: sharedBrowser }) => { browser = sharedBrowser; });

async function open(id, viewport = { width: 1440, height: 1100 }) {
  const page = await browser.newPage({ viewport });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(baseURL);
  await page.locator('.demo-select select').selectOption(id);
  await page.getByTestId('series-chart').scrollIntoViewIfNeeded();
  return { page, errors };
}

// The canvas is not readable, so sweep the pointer until the HTML tooltip names the year.
async function hoverYear(page, year) {
  const box = await page.locator('.chart-canvas canvas').boundingBox();
  for (let x = box.x; x < box.x + box.width; x += 2) {
    await page.mouse.move(x, box.y + box.height / 2);
    const tip = page.getByTestId('chart-tooltip');
    if (await tip.count() && (await tip.innerText()).startsWith(String(year))) return tip.innerText();
  }
  throw new Error(`No tooltip for ${year}`);
}

async function tableRows(page) {
  await page.locator('.chart-values > summary').click();
  return page.locator('.chart-values tbody tr').evaluateAll(rows => rows.map(row => [...row.children].map(cell => cell.textContent)));
}

test('station gaps stay gaps in the exact-value table and tooltips, never zero or joined', async () => {
  const { page, errors } = await open('kyiv-summer-heat');
  try {
    const r = cases['kyiv-summer-heat'];
    const station = new Map(r.witness.series.map(point => [point.year, point.value]));
    const band = new Map(r.sen.band.map(point => [point.year, point]));
    const gaps = r.witness.series.filter(point => point.value === null).map(point => point.year);
    assert.deepEqual(gaps, [2007, 2008, 2009, 2025]);
    const rows = await tableRows(page);
    assert.deepEqual(rows, r.series.map(point => {
      const { low, mid, high } = band.get(point.year);
      const measured = station.get(point.year);
      return [String(point.year), String(point.value), String(mid), `${low} to ${high}`, measured === null ? 'no station measurement' : String(measured)];
    }));
    const { low, mid, high } = band.get(2008);
    assert.equal(await hoverYear(page, 2008), `2008\nNASA POWER: 20.64 °C\nTrend: ${mid} °C · 95% band ${low} to ${high} °C\nStation: no station measurement`);
    assert.match(await hoverYear(page, 2006), /Station: 18\.74 °C/);
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('legend and captions carry units, period, station, the 95% band and the baseline from JSON', async () => {
  const { page, errors } = await open('kyiv-summer-heat');
  try {
    const chart = await page.getByTestId('series-chart').innerText();
    assert.match(chart, /Yearly summer \(Jun–Aug\) values, 1981–2025 · JJA · absolute values in °C/);
    assert.match(chart, /Trend \(Sen’s slope\): \+0\.6512 °C \/ decade over 1981–2025 · JJA/);
    assert.match(chart, /Shaded band: 95% uncertainty of the trend slope \(\+0\.4189 to \+0\.8952 °C \/ decade\), not the range of individual years\./);
    assert.match(chart, /Ground station Kyiv, 6 km away \(°C\)\. Breaks in the line are years with no station measurement/);
    const stripes = page.locator('.stripes > div');
    assert.equal(await stripes.count(), cases['kyiv-summer-heat'].series.length);
    assert.equal(await stripes.first().getAttribute('title'), '1981: 19.39 °C · 1991-2020 average: 20.35 °C');
    assert.match(await page.locator('.stripe-legend').innerText(), /Colour is relative to the 1991-2020 normal: 20\.35 °C, the average of 30 years\./);
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('a case without a station says so instead of drawing or zero-filling one', async () => {
  const { page, errors } = await open('lviv-drier');
  try {
    assert.match(await page.getByTestId('series-chart').innerText(), /No ground station for this place\. Only the NASA POWER series is shown\./);
    const rows = await tableRows(page);
    assert.ok(rows.every(row => row[4] === 'no station for this place'));
    assert.match(await hoverYear(page, 2000), /Station: none for this place/);
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('a cross-year winter season is named in captions and the chart fits a phone screen', async () => {
  const { page, errors } = await open('kyiv-winter-snow', { width: 390, height: 844 });
  try {
    assert.match(await page.locator('.year-stripes figcaption').innerText(), /Snow depth, 1982–2025 · DJF/);
    assert.match(await page.getByTestId('series-chart').innerText(), /Yearly winter \(Dec–Feb\) values/);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    const box = await page.getByTestId('series-chart').boundingBox();
    assert.ok(box.x >= 0 && box.x + box.width <= 390);
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('a record without a 1991–2020 normal names the whole-record average as its baseline', async () => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    const r = cases['global-warming-stopped'];
    assert.equal(r.baseline.kind, 'series_mean');
    // Not in the saved-case selector, so serve the canonical file through intercepted live endpoints.
    await page.route('**/api/variables', route => route.fulfill({ json: [r.variable] }));
    await page.route('**/api/places?*', route => route.fulfill({ json: [r.case.place] }));
    await page.route('**/api/check', route => route.fulfill({ json: r }));
    await page.goto(baseURL + '/?source=live');
    await page.getByLabel('Claim', { exact: true }).fill(r.case.claim_text);
    await page.getByLabel('Place', { exact: true }).fill('Th');
    await page.getByRole('button', { name: r.case.place.name, exact: true }).click();
    await page.getByRole('button', { name: 'Check claim', exact: true }).click();
    const legend = await page.locator('.stripe-legend').innerText();
    assert.match(legend, /Colour is relative to the average of the whole record, 1998-2025: 0\.753 °C over 28 years\./);
    assert.match(legend, /does not cover enough of 1991–2020 for a normal/);
    assert.equal(await page.locator('.stripes > div').first().getAttribute('title'), `1998: ${r.series[0].value} °C · 1998-2025 average: 0.753 °C`);
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});
