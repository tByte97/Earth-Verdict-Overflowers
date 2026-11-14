import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium } from 'playwright';
import { readFile, mkdir } from 'node:fs/promises';

const files = ['kyiv-summer-heat', 'lviv-drier', 'kyiv-winter-snow'];
const fixtures = await Promise.all(files.map(async id => ({ id, result: JSON.parse(await readFile(new URL(`../../data/cases/${id}.json`, import.meta.url), 'utf8')) })));
const edgeFixtures = JSON.parse(await readFile(new URL('./fixtures/synthetic-cases.json', import.meta.url), 'utf8'));
const baseURL = process.env.TEST_BASE_URL || 'http://127.0.0.1:5173';
let browser;
before(async () => {
  browser = await chromium.launch(process.env.BROWSER_EXECUTABLE
    ? { executablePath: process.env.BROWSER_EXECUTABLE, headless: true }
    : { channel: 'msedge', headless: true });
});
after(async () => { await browser?.close(); });

async function open(path = '/') {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(baseURL + path);
  return { page, errors };
}

test('first view is concise; every supplied number survives in the exact-value disclosure', async () => {
  const { page, errors } = await open();
  try {
    assert.equal(await page.getByRole('heading', { name: 'Confirmed', exact: true }).count(), 1);
    assert.match(await page.locator('.metric-value').innerText(), /\+0.6512.*°C \/ decade/);
    assert.match(await page.locator('.witness').innerText(), /Sources agree/);
    assert.equal(await page.locator('.technical .numeric-table').isVisible(), false);
    await page.locator('.technical > summary').click();
    function leaves(value) {
      if (typeof value === 'number' || value === null) return [value];
      return value && typeof value === 'object' ? Object.values(value).flatMap(leaves) : [];
    }
    const values = leaves(fixtures[0].result);
    assert.equal(await page.locator('.numeric-table tbody tr').count(), values.length);
    const cells = await page.locator('.numeric-table tbody tr td:nth-child(2)').allTextContents();
    assert.deepEqual(cells, values.map(value => value === null ? 'Not supplied (null)' : String(value)));
    assert.match(await page.locator('.technical .numeric-table').innerText(), /°C \/ year/);
    await page.locator('.technical > summary').click();
    await page.getByRole('button', { name: 'Data sources' }).click();
    assert.equal(await page.locator('.sources').getAttribute('open'), '');
    assert.equal(await page.getByRole('link', { name: 'Open source' }).count(), fixtures[0].result.provenance.length);
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('all verdicts, reasons and witness states render from saved JSON without computation', async () => {
  const { page, errors } = await open();
  try {
    for (const fixture of fixtures) {
      await page.getByLabel('Saved case').selectOption(fixture.id);
      assert.equal(await page.locator(`.verdict-${fixture.result.verdict}`).count(), 1);
      assert.equal(await page.locator(`.witness-${fixture.result.witness?.agreement ?? 'no_station'}`).count(), 1);
      if (fixture.result.verdict === 'not_proven') assert.equal(await page.getByText('Not enough evidence does not mean no change.', { exact: true }).isVisible(), true);
      await page.getByRole('button', { name: 'Check claim', exact: true }).click();
      await page.locator('.verdict').waitFor();
      assert.equal(await page.locator(`.verdict-${fixture.result.verdict}`).count(), 1);
    }
    await page.getByLabel('Saved case').selectOption('kyiv-summer-heat');
    await page.locator('.technical > summary').click();
    assert.match(await page.locator('.technical').innerText(), /1.11E-6/);
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('edited parameters clear stale results and unsupported demo requests fail honestly', async () => {
  const { page } = await open();
  try {
    await page.getByLabel('From', { exact: true }).fill('1990');
    assert.equal(await page.locator('.verdict').count(), 0);
    await page.getByRole('button', { name: 'Check claim', exact: true }).click();
    assert.match(await page.getByRole('alert').innerText(), /No saved backend response matches/);
    await page.getByLabel('From', { exact: true }).fill('2026');
    await page.getByRole('button', { name: 'Check claim', exact: true }).click();
    assert.match(await page.getByRole('alert').innerText(), /start must not be after/);
    await page.getByLabel('Place', { exact: true }).fill('Ky');
    await page.getByRole('button', { name: fixtures[0].result.case.place.name, exact: true }).click();
    await page.getByRole('button', { name: 'How to use' }).click();
    assert.equal(await page.getByRole('heading', { name: 'Your first check' }).isVisible(), true);
  } finally { await page.close(); }
});

test('live mode posts edited CaseSpec, renders backend verdict and reports server errors', async () => {
  const { page, errors } = await open();
  try {
    let sent;
    await page.route('**/api/variables', route => route.fulfill({ json: [fixtures[0].result.variable] }));
    await page.route('**/api/places?*', route => route.fulfill({ json: [fixtures[0].result.case.place] }));
    await page.route('**/api/check', async route => {
      sent = route.request().postDataJSON();
      const result = structuredClone(fixtures[1].result);
      result.case = sent;
      delete result.detection;
      delete result.mk.r1;
      await route.fulfill({ json: result });
    });
    await page.goto(baseURL + '/?source=live');
    await page.getByLabel('Claim direction').selectOption('decrease');
    await page.getByLabel('Claim', { exact: true }).fill('Summers are cooler');
    await page.getByRole('button', { name: 'Check claim', exact: true }).click();
    await page.getByRole('heading', { name: 'Refuted', exact: true }).waitFor();
    assert.equal(sent.claim_direction, 'decrease');
    assert.equal(sent.claim_text, 'Summers are cooler');
    assert.equal(await page.getByText('Shared backend snapshots', { exact: true }).count(), 0);
    await page.locator('.technical > summary').click();
    assert.ok((await page.locator('.technical').innerText()).includes(`${fixtures[1].result.variable.units} / decade`));
    const r1row = page.locator('.statistics > div').filter({ hasText: 'Residual autocorrelation' });
    assert.match(await r1row.innerText(), /Not supplied/);
    await page.route('**/api/check', route => route.fulfill({ status: 503, json: { error: { code: 'source_unavailable', message: 'NOAA did not respond' } } }));
    await page.getByRole('button', { name: 'Check claim', exact: true }).click();
    await page.getByRole('alert').waitFor();
    assert.match(await page.getByRole('alert').innerText(), /NOAA did not respond/);
    assert.equal(await page.locator('.verdict').count(), 0);
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('a slow previous response cannot overwrite parameters edited during a check', async () => {
  const { page, errors } = await open();
  try {
    await page.route('**/api/variables', route => route.fulfill({ json: [fixtures[0].result.variable] }));
    let release;
    const gate = new Promise(resolve => { release = resolve; });
    await page.route('**/api/check', async route => {
      await gate;
      await route.fulfill({ json: fixtures[0].result }).catch(() => {});
    });
    await page.goto(baseURL + '/?source=live');
    const outgoing = page.waitForRequest('**/api/check');
    await page.getByRole('button', { name: 'Check claim', exact: true }).click();
    await outgoing;
    await page.getByLabel('From', { exact: true }).fill('2000');
    release();
    await page.waitForTimeout(300);
    assert.equal(await page.locator('.verdict').count(), 0);
    assert.equal(await page.getByLabel('From', { exact: true }).inputValue(), '2000');
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('desktop and mobile layouts have no page overflow and produce review screenshots', async () => {
  const { page, errors } = await open();
  try {
    await mkdir(new URL('../test-results/', import.meta.url), { recursive: true });
    await page.screenshot({ path: 'test-results/verdict-desktop.png', fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: 'test-results/verdict-mobile.png', fullPage: true });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.getByLabel('Saved case').selectOption('kyiv-winter-snow');
    await page.locator('.technical > summary').click();
    await page.screenshot({ path: 'test-results/verdict-not-proven-details.png', fullPage: true });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});


test('canonical contract units, residual r1, witness gaps, provenance and future separation are preserved', async () => {
  const { page, errors } = await open();
  try {
    await page.locator('.technical > summary').click();
    const r1row = page.locator('.statistics > div').filter({ hasText: 'Residual autocorrelation' });
    assert.match(await r1row.innerText(), /dimensionless\s+0/);
    const ci = page.locator('.statistics > div').filter({ hasText: 'Sen 95%' });
    assert.match(await ci.innerText(), /0.4189 to 0.8952.*°C \/ decade/);
    assert.equal(await page.locator('.technical .numeric-table tbody tr').filter({ hasText: 'witness.series.26.value' }).getByText('Not supplied (null)', { exact: true }).count(), 1);
    assert.equal(await page.locator('.technical .numeric-table tbody tr').filter({ hasText: 'scenarios.paths' }).count(), 0);
    const witnessRow = page.locator('.technical .numeric-table tbody tr').filter({ has: page.locator('code', { hasText: /^witness.sen.slope_per_decade$/ }) });
    await witnessRow.getByRole('button', { name: 'NOAA NCEI' }).click();
    assert.equal(await page.locator('.sources').getAttribute('open'), '');
    assert.equal(await page.locator('.source-record').filter({ hasText: 'NOAA NCEI' }).isVisible(), true);
    const verdict = await page.locator('.verdict').innerText();
    await page.locator('.future-reference > summary').click();
    assert.match(await page.locator('.future-reference').innerText(), /stylised placeholders, not CMIP6/);
    assert.match(await page.locator('.future-reference').innerText(), /1995-2014/);
    assert.equal(await page.locator('.verdict').innerText(), verdict);
    const dimensions = await page.locator('.future-reference tbody tr').filter({ hasText: 'scenarios.paths.0.median.0' }).innerText();
    assert.match(dimensions, /°C/);
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('all edge-case reasons and witness agreements still render using test-only intercepted responses', async () => {
  const { page, errors } = await open();
  try {
    await page.route('**/api/variables', route => route.fulfill({ json: [fixtures[0].result.variable] }));
    for (const fixture of edgeFixtures) {
      await page.route('**/api/check', route => route.fulfill({ json: fixture.result }));
      await page.goto(baseURL + '/?source=live');
      await page.getByRole('button', { name: 'Check claim', exact: true }).click();
      await page.locator('.verdict').waitFor();
      assert.equal(await page.locator(`.verdict-${fixture.result.verdict}`).count(), 1);
      assert.equal(await page.locator(`.witness-${fixture.result.witness?.agreement ?? 'no_station'}`).count(), 1);
      if (fixture.result.verdict === 'not_proven') assert.equal(await page.getByText('Not enough evidence does not mean no change.', { exact: true }).isVisible(), true);
    }
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});
