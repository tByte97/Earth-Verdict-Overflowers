import { test, expect } from '@playwright/test';
import assert from 'node:assert/strict';
import { readFile, mkdir } from 'node:fs/promises';

const files = ['kyiv-summer-heat', 'lviv-drier', 'kyiv-winter-snow'];
const fixtures = await Promise.all(files.map(async id => ({ id, result: JSON.parse(await readFile(new URL(`../../data/cases/${id}.json`, import.meta.url), 'utf8')) })));
const edgeFixtures = JSON.parse(await readFile(new URL('./fixtures/synthetic-cases.json', import.meta.url), 'utf8'));
const baseURL = process.env.TEST_BASE_URL || 'http://127.0.0.1:4173';
let browser;
test.beforeAll(async ({ browser: sharedBrowser }) => { browser = sharedBrowser; });

async function configureLive(page) {
  await page.route('**/api/places?*', route => route.fulfill({ json: [fixtures[0].result.case.place] }));
  await expect(page.getByRole('combobox', { name: 'Variable', exact: true })).toBeEnabled();
  await page.getByLabel('Claim', { exact: true }).fill('Test claim');
  await page.getByLabel('Place', { exact: true }).fill('Ky');
  await page.getByRole('button', { name: fixtures[0].result.case.place.name, exact: true }).click();
}

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
    function leaves(value, prefix = '') {
      if (typeof value === 'number' || value === null) return [[prefix, value]];
      return value && typeof value === 'object' ? Object.entries(value).flatMap(([key, child]) => leaves(child, prefix ? `${prefix}.${key}` : key)) : [];
    }
    const values = new Map(leaves(fixtures[0].result));
    const rows = await page.locator('.numeric-table tbody tr').evaluateAll(items => items.map(row => [row.querySelector('code').textContent, row.querySelector('td').textContent]));
    assert.equal(rows.length, values.size);
    rows.forEach(([path, cell]) => values.get(path) === null ? assert.match(cell, /\(null\)$/) : assert.equal(cell, String(values.get(path))));
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
      result.verdict = 'refuted';
      result.reason = 'opposite_trend';
      await route.fulfill({ json: result });
    });
    await page.goto(baseURL + '/?source=live');
    await configureLive(page);
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
    assert.match(await r1row.innerText(), /dimensionless\s+0/);
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
    await configureLive(page);
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
    const witnessRow = page.locator('.technical .numeric-table tbody tr').filter({ has: page.locator('code', { hasText: /^witness.series.0.value$/ }) });
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
      const result = structuredClone(fixtures[0].result);
      result.verdict = fixture.result.verdict;
      result.reason = fixture.result.reason;
      result.years_to_wait = fixture.result.years_to_wait;
      if (fixture.result.witness === null) result.witness = null;
      else result.witness.agreement = fixture.result.witness.agreement;
      await page.route('**/api/check', route => route.fulfill({ json: result }));
      await page.goto(baseURL + '/?source=live');
    await configureLive(page);
      await page.getByRole('button', { name: 'Check claim', exact: true }).click();
      await page.locator('.verdict').waitFor();
      assert.equal(await page.locator(`.verdict-${fixture.result.verdict}`).count(), 1);
      assert.equal(await page.locator(`.witness-${fixture.result.witness?.agreement ?? 'no_station'}`).count(), 1);
      if (fixture.result.verdict === 'not_proven') assert.equal(await page.getByText('Not enough evidence does not mean no change.', { exact: true }).isVisible(), true);
    }
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});


test('detection shows total duration and additional wait from the same updated backend response', async () => {
  const { page, errors } = await open();
  try {
    for (const fixture of fixtures) {
      await page.getByLabel('Saved case').selectOption(fixture.id);
      await page.locator('.technical > summary').click();
      const detection = page.getByRole('region', { name: 'Detection duration' });
      const index = fixture.result.detection.multipliers.indexOf(1);
      assert.equal(await detection.getByTestId('detection-total').innerText(), String(fixture.result.detection.years_needed[index]));
      assert.equal(await detection.getByTestId('detection-wait').innerText(), fixture.result.years_to_wait === null ? 'Not applicable' : String(fixture.result.years_to_wait));
      if (fixture.result.years_to_wait !== null) assert.equal(fixture.result.detection.years_needed[index] - fixture.result.detection.n_years, fixture.result.years_to_wait);
    }
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('rate control uses exact nodes, log interpolation, and never changes the verdict or backend wait', async () => {
  const { page, errors } = await open();
  try {
    await page.getByLabel('Saved case').selectOption('lviv-drier');
    await page.locator('.technical > summary').click();
    const detection = page.getByRole('region', { name: 'Detection duration' });
    const originalVerdict = await page.locator('.verdict').innerText();
    const originalWait = await detection.getByTestId('detection-wait').innerText();
    const data = fixtures[1].result.detection;
    for (const [i, rate] of data.multipliers.entries()) {
      await detection.getByRole('button', { name: `×${rate}`, exact: true }).click();
      assert.equal(await detection.getByTestId('detection-total').innerText(), String(data.years_needed[i]));
    }
    await detection.getByRole('button', { name: '×0.75', exact: true }).click();
    await detection.getByRole('slider').focus();
    await detection.getByRole('slider').press('ArrowRight');
    const rate = Number(await detection.getByRole('slider').inputValue());
    assert.ok(rate > 0.75 && rate < 1);
    const t = (Math.log(rate) - Math.log(0.75)) / (Math.log(1) - Math.log(0.75));
    const expected = Math.exp(Math.log(data.years_needed[1]) + t * (Math.log(data.years_needed[2]) - Math.log(data.years_needed[1])));
    assert.ok(Math.abs(Number(await detection.getByTestId('detection-total').innerText()) - expected) < 0.01);
    assert.match(await detection.innerText(), /Interpolated illustration/);
    assert.equal(await detection.getByTestId('detection-wait').innerText(), originalWait);
    assert.equal(await page.locator('.verdict').innerText(), originalVerdict);
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('missing detection points are not zero or bridged and null waiting retains its meaning', async () => {
  const { page, errors } = await open();
  try {
    await page.route('**/api/variables', route => route.fulfill({ json: [fixtures[0].result.variable] }));
    const result = structuredClone(fixtures[1].result);
    result.years_to_wait = null;
    result.detection.years_needed[1] = null;
    result.detection.years_needed[2] = result.detection.n_years;
    await page.route('**/api/check', route => route.fulfill({ json: result }));
    await page.goto(baseURL + '/?source=live');
    await configureLive(page);
    await page.getByRole('button', { name: 'Check claim', exact: true }).click();
    await page.locator('.verdict').waitFor();
    await page.locator('.technical > summary').click();
    const detection = page.getByRole('region', { name: 'Detection duration' });
    assert.equal(await detection.getByTestId('detection-wait').innerText(), 'Not determined');
    assert.match(await detection.innerText(), /already been reached.*remains unproven/);
    await detection.getByRole('button', { name: '×0.75', exact: true }).click();
    assert.equal(await detection.getByTestId('detection-total').innerText(), 'Not determined for this rate');
    await detection.getByRole('slider').focus();
    await detection.getByRole('slider').press('ArrowRight');
    assert.equal(await detection.getByTestId('detection-total').innerText(), 'Not determined for this rate');
    assert.equal(await page.getByText('Not enough evidence does not mean no change.', { exact: true }).isVisible(), true);
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('live catalogue initializes the actual POST variable and announces distinct lifecycle states', async () => {
  const { page, errors } = await open();
  try {
    const variable = { ...fixtures[0].result.variable, id: 'backend-only-variable', label: 'Backend-only variable' };
    let release;
    const ready = new Promise(resolve => { release = resolve; });
    await page.route('**/api/variables', async route => { await ready; await route.fulfill({ json: [variable] }); });
    let sent;
    await page.route('**/api/check', async route => {
      sent = route.request().postDataJSON();
      await route.fulfill({ status: 503, json: { error: { code: 'source_unavailable', message: 'Data unavailable' } } });
    });
    await page.goto(baseURL + '/?source=live');
    await expect(page.locator('#result-status')).toHaveText('Loading available variables.');
    await expect(page.getByRole('button', { name: 'Check claim', exact: true })).toBeDisabled();
    release();
    await expect(page.locator('#result-status')).toHaveText('Ready to configure a check.');
    await expect(page.getByRole('combobox', { name: 'Variable', exact: true })).toHaveValue(variable.id);
    await expect(page.getByLabel('Claim', { exact: true })).toHaveValue('');
    await expect(page.getByLabel('Place', { exact: true })).toHaveValue('');
    await configureLive(page);
    await expect(page.locator('#result-status')).toHaveText('Parameters changed. Run a check to see the result.');
    await page.getByRole('button', { name: 'Check claim', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('Data unavailable');
    assert.equal(sent.variable_id, variable.id);
    await expect(page.locator('#result-status')).toHaveText('Check unavailable. Data unavailable');
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('empty live catalogue is an explicit error and never submits a demo variable', async () => {
  const { page, errors } = await open();
  try {
    await page.route('**/api/variables', route => route.fulfill({ json: [] }));
    await page.goto(baseURL + '/?source=live');
    await expect(page.getByRole('alert')).toContainText('Invalid or empty variable catalogue');
    await expect(page.getByRole('combobox', { name: 'Variable', exact: true })).toContainText('No variables available');
    await expect(page.getByRole('button', { name: 'Check claim', exact: true })).toBeDisabled();
    await expect(page.locator('#result-status')).toContainText('Check unavailable.');
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('malformed nested responses are rejected before rendering, with the page still usable', async () => {
  const { page, errors } = await open();
  try {
    await page.route('**/api/variables', route => route.fulfill({ json: [fixtures[0].result.variable] }));
    await page.goto(baseURL + '/?source=live');
    await configureLive(page);
    const mutations = [
      r => { delete r.variable.label; },
      r => { r.case.season = []; },
      r => { delete r.reason; },
      r => { r.robustness_summary.total = 'five'; },
      r => { r.witness.station.name = null; },
      r => { r.witness.agreement = 'no_station'; },
      r => { r.witness.rates = { common_years: 20 }; },
      r => { r.extrapolation.years = {}; },
      r => { r.extrapolation.paths[0].central = []; },
      r => { r.scenarios.paths[0].median = 'invalid'; },
      r => { r.scenarios.baseline_period = null; },
      r => { delete r.detection; },
      r => { r.detection.multipliers = null; },
    ];
    for (const mutate of mutations) {
      const result = structuredClone(fixtures[0].result);
      mutate(result);
      await page.route('**/api/check', route => route.fulfill({ json: result }));
      await page.getByRole('button', { name: 'Check claim', exact: true }).click();
      await expect(page.getByRole('alert')).toContainText('Invalid CheckResult response');
      assert.equal(await page.locator('.verdict').count(), 0);
      await expect(page.getByRole('button', { name: 'Check claim', exact: true })).toBeEnabled();
    }
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('optional witness rates and nullable source versions are accepted without losing values', async () => {
  const { page, errors } = await open();
  try {
    const result = structuredClone(fixtures[0].result);
    result.provenance[0].version = null;
    result.witness.rates = { common_years: 30, main_slope_per_decade: 0.6, witness_slope_per_decade: 0.7, difference_per_decade: 0.1, ci_low: -0.2, ci_high: 0.4, p: 0.3, consistent: true };
    await page.route('**/api/variables', route => route.fulfill({ json: [result.variable] }));
    await page.route('**/api/check', route => route.fulfill({ json: result }));
    await page.goto(baseURL + '/?source=live');
    await configureLive(page);
    await page.getByRole('button', { name: 'Check claim', exact: true }).click();
    await page.locator('.verdict').waitFor();
    await page.locator('.technical > summary').click();
    const row = page.locator('.technical tbody tr').filter({ has: page.locator('code', { hasText: /^witness.rates.difference_per_decade$/ }) });
    await expect(row).toContainText('0.1');
    await expect(row).toContainText('°C / decade');
    await expect(row.getByRole('button')).toHaveText('Backend statistics');
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('derived provenance uses method records regardless of free-text descriptions or record order', async () => {
  const { page, errors } = await open();
  try {
    const result = structuredClone(fixtures[0].result);
    result.provenance.reverse();
    result.provenance.forEach(record => { record.what = 'Translated description without source role'; });
    await page.route('**/api/variables', route => route.fulfill({ json: [result.variable] }));
    await page.route('**/api/check', route => route.fulfill({ json: result }));
    await page.goto(baseURL + '/?source=live');
    await configureLive(page);
    await page.getByRole('button', { name: 'Check claim', exact: true }).click();
    await page.locator('.verdict').waitFor();
    await page.locator('.technical > summary').click();
    const row = path => page.locator('.numeric-table tbody tr').filter({ has: page.locator('code', { hasText: new RegExp(`^${path.replaceAll('.', '\\.')}\u0024`) }) });
    await expect(row('detection.years_needed.2').getByRole('button')).toHaveText('Detection simulation');
    await row('detection.years_needed.2').getByRole('button').click();
    await expect(page.locator('.sources')).toHaveAttribute('open', '');
    await expect(page.locator('.sources h4').filter({ hasText: /^Detection simulation$/ })).toBeVisible();
    await expect(row('series.0.value').getByRole('button')).toHaveText('NASA POWER');
    await page.locator('.future-reference > summary').click();
    await expect(row('extrapolation.paths.0.central.0').getByRole('button')).toHaveText('Trend extrapolation');
    await expect(row('scenarios.paths.0.median.0').getByRole('button')).toHaveText('Stylised scenario');
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('null caveat and missing station do not leave empty or dangling descriptions', async () => {
  const { page, errors } = await open();
  try {
    const result = structuredClone(fixtures[1].result);
    result.variable.caveat = null;
    await page.route('**/api/variables', route => route.fulfill({ json: [result.variable] }));
    await page.route('**/api/check', route => route.fulfill({ json: result }));
    await page.goto(baseURL + '/?source=live');
    await configureLive(page);
    await page.getByRole('button', { name: 'Check claim', exact: true }).click();
    await page.locator('.verdict').waitFor();
    assert.equal(await page.locator('p.data-note:empty').count(), 0);
    await expect(page.locator('.witness p')).toHaveText('No suitable ground station is available.');
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('rendering failures recover through the error boundary instead of a blank page', async () => {
  const { page } = await open('/tests/error-boundary.html');
  try {
    await expect(page.getByRole('alert')).toContainText('We could not display this result.');
    await expect(page.getByRole('link', { name: 'Open saved cases' })).toHaveAttribute('href', '/');
  } finally { await page.close(); }
});

test('unknown cities do not inherit Kyiv aliases', async () => {
  const { page, errors } = await open();
  try {
    const result = await page.evaluate(async () => {
      const { matchesPlace } = await import('/src/places.ts');
      const warsaw = { place_id: 'city:warsaw', name: 'Warsaw', lat: 52.23, lon: 21.01 };
      return [matchesPlace(warsaw, 'Kyiv'), matchesPlace(warsaw, 'Київ'), matchesPlace(warsaw, 'Wars')];
    });
    assert.deepEqual(result, [false, false, true]);
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});
