import { expect, test } from '@playwright/test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const files = ['kyiv-summer-heat', 'lviv-drier', 'kyiv-winter-snow'];
const cases = Object.fromEntries(await Promise.all(files.map(async id => [id, JSON.parse(await readFile(new URL(`../../data/cases/${id}.json`, import.meta.url), 'utf8'))])));
const baseURL = process.env.TEST_BASE_URL || 'http://127.0.0.1:4173';
const order = ['raw', 'season', 'yearly', 'trend', 'random_check', 'robustness', 'witness', 'verdict'];
let browser;
test.beforeAll(async ({ browser: sharedBrowser }) => { browser = sharedBrowser; });

async function open(id, viewport = { width: 1440, height: 1100 }) {
  const page = await browser.newPage({ viewport });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  // Live mode lists /api/cases; an empty list keeps these tests on the form path.
  await page.route('**/api/cases', route => route.fulfill({ json: [] }));
  await page.goto(baseURL);
  await page.locator(`[data-case="${id}"]`).click();
  return { page, errors, steps: page.locator('.step-pipeline') };
}

test('all eight steps appear in pipeline order with the backend text unchanged', async () => {
  for (const id of files) {
    const { page, errors, steps } = await open(id, id === 'lviv-drier' ? { width: 390, height: 844 } : undefined);
    try {
      assert.deepEqual(await steps.locator('li.pipeline-step').evaluateAll(items => items.map(item => item.dataset.step)), order);
      for (const step of cases[id].steps) {
        const text = await steps.locator(`li[data-step="${step.id}"]`).innerText();
        for (const part of [step.title, step.value, step.detail]) assert.ok(text.includes(part), `${id} ${step.id}: ${part}`);
      }
      if (id === 'lviv-drier') assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
      assert.deepEqual(errors, []);
    } finally { await page.close(); }
  }
});

test('mini visuals come from existing fields only', async () => {
  const { page, errors, steps } = await open('kyiv-summer-heat');
  try {
    const r = cases['kyiv-summer-heat'];
    const step = id => steps.locator(`li[data-step="${id}"]`);
    assert.equal(await step('season').locator('svg').getAttribute('aria-label'), 'Months used: 6, 7, 8');
    assert.equal(await step('season').locator('.month-on').count(), 3);
    assert.equal(await step('yearly').locator('path.spark-series').count(), 1);
    assert.equal(await step('trend').locator('polygon.trend-band').count(), 1);
    assert.equal(await step('raw').locator('svg').getAttribute('aria-label'), `Sparkline of ${r.steps[0].n_months} monthly values`);
    assert.match(await step('random_check').innerText(), /Threshold: p below 0\.05 · Sen\/Mann–Kendall and least squares agree/);
    assert.match(await step('trend').locator('.step-fields').innerText(), /sen\.slope_per_decade/);
    assert.equal(await step('trend').locator('.step-fields dd').first().innerText(), `${r.sen.slope_per_decade} °C / decade`);
    assert.deepEqual(await step('robustness').locator('rect').evaluateAll(rects => rects.map(rect => rect.getAttribute('class'))), r.robustness.map(w => w.significant ? 'window-on' : 'window-off'));
    // Station gaps split the line: 2007–2009 and 2025 are null, so the path has two runs.
    assert.equal((await step('witness').locator('path.spark-station').getAttribute('d')).match(/M/g).length, 2);
    assert.equal(await step('verdict').locator('.step-verdict-confirmed').innerText(), '✓');
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
  const other = await open('kyiv-winter-snow');
  try {
    const step = id => other.steps.locator(`li[data-step="${id}"]`);
    assert.equal(await step('season').locator('svg').getAttribute('aria-label'), 'Months used: 12, 1, 2');
    assert.equal(await step('witness').locator('svg').count(), 0);
    assert.equal(await step('witness').getByRole('button').count(), 0);
    // Snow: Sen/Mann–Kendall and least squares point in different directions.
    assert.match(await step('random_check').innerText(), /Caution: the methods disagree on the direction/);
    assert.deepEqual(other.errors, []);
  } finally { await other.page.close(); }
});

test('each step source opens its provider or method record in one click', async () => {
  const { page, errors, steps } = await open('kyiv-summer-heat');
  try {
    for (const [id, name, record] of [['raw', 'NASA POWER', 'NASA POWER'], ['witness', 'NOAA NCEI', 'NOAA NCEI'], ['random_check', 'Backend statistics', 'Backend statistics']]) {
      await page.locator('.sources').evaluate(element => { element.open = false; });
      await steps.locator(`li[data-step="${id}"]`).getByRole('button', { name, exact: true }).click();
      assert.equal(await page.locator('.sources').getAttribute('open'), '');
      assert.equal(await page.locator('.source-record').filter({ hasText: record }).first().isVisible(), true);
    }
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('a step missing from the response is reported, not skipped', async () => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    const r = structuredClone(cases['kyiv-summer-heat']);
    r.steps = r.steps.filter(step => step.id !== 'robustness');
    await page.route('**/api/variables', route => route.fulfill({ json: [r.variable] }));
    await page.route('**/api/places?*', route => route.fulfill({ json: [r.case.place] }));
    await page.route('**/api/check', route => route.fulfill({ json: r }));
    await page.goto(baseURL + '/?source=live');
    await page.getByLabel('Claim', { exact: true }).fill(r.case.claim_text);
    await page.getByLabel('Place', { exact: true }).fill('Ky');
    await page.getByRole('button', { name: r.case.place.name, exact: true }).click();
    await page.getByRole('button', { name: 'Check claim', exact: true }).click();
    const steps = page.locator('.step-pipeline li.pipeline-step');
    await expect(steps).toHaveCount(8);   // waits for the response to render
    assert.match(await page.locator('li[data-step="robustness"]').innerText(), /Step not supplied by the backend/);
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});
