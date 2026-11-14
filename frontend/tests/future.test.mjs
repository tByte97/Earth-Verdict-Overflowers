import { test } from '@playwright/test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const load = async id => JSON.parse(await readFile(new URL(`../../data/cases/${id}.json`, import.meta.url), 'utf8'));
const heat = await load('kyiv-summer-heat');
const lviv = await load('lviv-drier');
const baseURL = process.env.TEST_BASE_URL || 'http://127.0.0.1:4173';
const codes = { ssp126: 'SSP1-2.6', ssp245: 'SSP2-4.5', ssp585: 'SSP5-8.5' };
// Same display formatting as src/format.ts `number`.
const fmt = (value, signed = false) => {
  const text = new Intl.NumberFormat('en', { maximumSignificantDigits: 5 }).format(value);
  return signed && value > 0 ? `+${text}` : text;
};
let browser;
test.beforeAll(async ({ browser: sharedBrowser }) => { browser = sharedBrowser; });

async function open(id, viewport = { width: 1440, height: 1100 }) {
  const page = await browser.newPage({ viewport });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(baseURL);
  await page.locator('.demo-select select').selectOption(id);
  await page.locator('.future-reference > summary').click();
  return { page, errors, chart: page.getByTestId('future-chart') };
}

// Everything in the card outside the future disclosure.
const verdictText = page => page.locator('.verdict-card').evaluate(card => {
  const copy = card.cloneNode(true);
  copy.querySelector('.future-reference')?.remove();
  return copy.innerText;
});

test('every scenario path and year reads exactly from JSON and never changes the verdict card', async () => {
  const { page, errors, chart } = await open('kyiv-summer-heat');
  try {
    const before = await verdictText(page);
    const status = await page.locator('#result-status').innerText();
    for (const path of heat.scenarios.paths) {
      await chart.getByRole('group', { name: 'Emissions path' }).getByRole('button', { name: new RegExp(path.label) }).click();
      for (const [i, year] of path.years.entries()) {
        await chart.getByRole('group', { name: 'Scenario year' }).getByRole('button', { name: String(year), exact: true }).click();
        assert.equal(await chart.getByTestId('scenario-readout').innerText(),
          `${year} · ${path.label} ${codes[path.id]}: ${fmt(path.median[i], true)} °C change from the ${heat.scenarios.baseline_period} average (models range ${fmt(path.low[i], true)} to ${fmt(path.high[i], true)} °C)`);
        assert.equal(await verdictText(page), before);
      }
    }
    assert.equal(await page.locator('#result-status').innerText(), status);
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('every what-if pace and year reads exactly from JSON and never changes the verdict card', async () => {
  const { page, errors, chart } = await open('kyiv-summer-heat');
  try {
    const before = await verdictText(page);
    const ext = heat.extrapolation;
    for (const path of ext.paths) {
      await chart.getByRole('group', { name: 'Pace' }).getByRole('button', { name: path.label, exact: true }).click();
      for (const year of [ext.years[0], 2040, ext.years.at(-1)]) {
        const i = ext.years.indexOf(year);
        await chart.getByLabel('What-if year').selectOption(String(year));
        assert.equal(await chart.getByTestId('extrapolation-readout').innerText(),
          `${year} · ${path.label}: ${fmt(path.central[i])} °C (95% range ${fmt(path.low[i])} to ${fmt(path.high[i])} °C)`);
      }
    }
    assert.equal(await verdictText(page), before);
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('future zone, notes, baseline, path names and SSP codes are labelled from JSON', async () => {
  const { page, errors, chart } = await open('kyiv-summer-heat');
  try {
    const text = await chart.innerText();
    assert.match(text, /Looking ahead · not a forecast/);
    assert.match(text, /These lines do not change the verdict above/);
    assert.match(text, /Past observations · 1981–2025/);
    assert.ok(text.includes(heat.extrapolation.note));
    assert.ok(text.includes(heat.scenarios.note));
    assert.ok(text.includes(`Source: ${heat.scenarios.source}.`));
    assert.match(text, /0 = the 1995-2014 average: 20\.31 °C \(observed\)/);
    assert.match(text, /Lines join the model periods; values between them are not model output\./);
    for (const path of heat.scenarios.paths) {
      assert.equal(await chart.getByRole('button', { name: new RegExp(path.label) }).locator('small').innerText(), codes[path.id]);
    }
    assert.deepEqual(await chart.getByRole('group', { name: 'Scenario year' }).getByRole('button').allInnerTexts(), heat.scenarios.paths[1].years.map(String));
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});

test('a case without scenarios keeps the what-if line and says scenarios are missing', async () => {
  const { page, errors, chart } = await open('lviv-drier', { width: 390, height: 844 });
  try {
    assert.equal(lviv.scenarios, null);
    assert.match(await chart.innerText(), /No climate-model scenarios for this case\./);
    assert.equal(await chart.getByRole('group', { name: 'Emissions path' }).count(), 0);
    assert.match(await chart.getByTestId('extrapolation-readout').innerText(), /^2050 · Same pace as 1981–2025: 807\.3 mm/);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    assert.deepEqual(errors, []);
  } finally { await page.close(); }
});
