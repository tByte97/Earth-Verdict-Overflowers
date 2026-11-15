import { test, expect } from '@playwright/test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const ids = ['kyiv-summer-heat', 'lviv-drier', 'kyiv-winter-snow', 'kyiv-colder', 'kyiv-summer-rain', 'global-warming-stopped'];
const cases = Object.fromEntries(await Promise.all(ids.map(async id => [id, JSON.parse(await readFile(new URL(`../../data/cases/${id}.json`, import.meta.url), 'utf8'))])));

// The UI shows numbers with up to five significant digits; the exact values stay in the exact-value table.
const fmt = value => new Intl.NumberFormat('en', { maximumSignificantDigits: 5 }).format(value);

test.beforeEach(async ({ page }) => {
  await page.route('https://gibs.earthdata.nasa.gov/**', route => route.abort());
});

async function liveCases(page, list, responses) {
  await page.route('**/api/variables', route => route.fulfill({ json: [cases['kyiv-summer-heat'].variable] }));
  await page.route('**/api/cases', route => route.fulfill({ json: list.map(id => ({ id, claim_text: responses[id]?.case.claim_text ?? cases[id].case.claim_text, place: 'x', variable_id: 'x', verdict: 'x' })) }));
  await page.route('**/api/cases/*', route => {
    const id = decodeURIComponent(route.request().url().split('/').pop());
    return responses[id] ? route.fulfill({ json: responses[id] }) : route.fulfill({ status: 500, json: { error: { code: 'internal', message: 'Case failed' } } });
  });
}

test('the case grid lists every saved case with variable and season, and the first case is open', async ({ page }) => {
  await page.goto('/');
  const buttons = page.locator('.cases .case');
  await expect(buttons).toHaveCount(ids.length);
  for (const id of ids) {
    const r = cases[id];
    const button = page.locator(`[data-case="${id}"]`);
    await expect(button.locator('b')).toHaveText(r.case.claim_text);
    await expect(button.locator('span')).toContainText(r.variable.label);
  }
  await expect(page.locator('[data-case="kyiv-summer-heat"] span')).toHaveText('Air temperature · Summer');
  await expect(page.locator('[data-case="kyiv-summer-heat"]')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('.case[aria-pressed="true"]')).toHaveCount(1);
  await expect(page.locator('.case-parameters')).not.toHaveAttribute('open', '');
  await expect(page.locator('.case-parameters > summary')).toHaveText('Check your own claim');
});

test('the verdict hero shows the backend numbers and sentences for a confirmed case', async ({ page }) => {
  await page.goto('/');
  const r = cases['kyiv-summer-heat'];
  const hero = page.locator('.hero');
  await expect(hero.locator('.where')).toHaveText('Kyiv · 50.45° N, 30.52° E · ~50 km cell');
  await expect(hero.locator('.metric-value')).toHaveText(`+${r.sen.slope_per_decade}°C per decade`);
  await expect(hero.getByRole('heading', { name: 'Confirmed', exact: true })).toBeVisible();
  const text = await hero.locator('.hero-text').first().innerText();
  assert.ok(text.includes(`From 1981 to 2025, summer air temperature here went from about ${r.sen.band[0].mid} to ${r.sen.band.at(-1).mid} °C.`), text);
  assert.ok(text.includes('less than 1 in 1,000 times'), text);
  const facts = await hero.locator('.fact').evaluateAll(items => items.map(item => [item.querySelector('dt').textContent, item.querySelector('dd').textContent]));
  assert.deepEqual(facts, [['p-value', '1.11E-6'], ['95% range, per decade', `+${r.sen.ci_low} … +${r.sen.ci_high} °C`], ['Signal emerged', String(r.detection_history.emerged_year)]]);
  await expect(hero.locator('.warn')).toHaveCount(0);
});

test('not proven keeps its caveat, the backend waiting estimate and an empty emergence tile', async ({ page }) => {
  await page.goto('/');
  await page.locator('[data-case="lviv-drier"]').click();
  const r = cases['lviv-drier'];
  const hero = page.locator('.hero');
  await expect(hero.getByRole('heading', { name: 'Not proven', exact: true })).toBeVisible();
  await expect(hero).toContainText('A pattern like this can come from natural ups and downs alone');
  await expect(hero).not.toContainText('less than 1 in');
  await expect(hero).toContainText('Not proven does not mean no change.');
  await expect(hero).toContainText(`about ${r.years_to_wait} more years of observations`);
  await expect(hero.locator('.fact').nth(0).locator('dd')).toHaveText(String(r.mk.p));
  await expect(hero.locator('.fact').nth(2).locator('dd')).toHaveText('—');
});

test('a region case shows the whole planet without coordinates', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  await page.locator('[data-case="global-warming-stopped"]').click();
  await expect(page.locator('.hero .where')).toHaveText(cases['global-warming-stopped'].case.place.name);
  await expect(page.locator('.globe-proj')).toHaveText('3D globe');
  await page.locator('[data-case="kyiv-colder"]').click();
  await expect(page.locator('.globe-proj')).toHaveText('2D map · Web Mercator');
});

test('opening a case flies with the claim as the flight title; reduced motion skips the flight', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('.globe')).not.toHaveAttribute('data-state', 'loading', { timeout: 20_000 });
  await page.locator('[data-case="kyiv-colder"]').click();
  await expect(page.locator('.globe')).toHaveAttribute('data-flight', 'true');
  await expect(page.locator('.flight-title span')).toHaveText(cases['kyiv-colder'].case.claim_text);
  await expect(page.locator('.globe')).not.toHaveAttribute('data-flight', 'true', { timeout: 10_000 });

  await page.emulateMedia({ reducedMotion: 'reduce' });
  let flew = false;
  await page.exposeFunction('sawFlight', () => { flew = true; });
  await page.locator('.globe').evaluate(globe => new MutationObserver(() => { if (globe.hasAttribute('data-flight')) window.sawFlight(); }).observe(globe, { attributes: true }));
  await page.locator('[data-case="lviv-drier"]').click();
  await expect(page.locator('.hero .where')).toContainText('Lviv');
  await page.waitForTimeout(500);
  assert.equal(flew, false);
  await expect(page.locator('.flight-title')).toHaveCSS('opacity', '0');
});

test('#case links round-trip and editing parameters drops the case from the URL', async ({ page }) => {
  await page.goto('/?source=saved');
  await page.locator('[data-case="kyiv-colder"]').click();
  await expect(page).toHaveURL(/\?source=saved#case=kyiv-colder$/);
  await page.goto('/?source=saved#case=kyiv-summer-rain');
  await expect(page.locator('[data-case="kyiv-summer-rain"]')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('.hero .metric-value')).toContainText(fmt(cases['kyiv-summer-rain'].sen.slope_per_decade));
  await page.evaluate(() => { window.location.hash = '#case=lviv-drier'; });
  await expect(page.locator('[data-case="lviv-drier"]')).toHaveAttribute('aria-pressed', 'true');
  await page.locator('.case-parameters > summary').click();
  await page.getByLabel('Claim', { exact: true }).fill('My own claim');
  await expect(page.locator('.case[aria-pressed="true"]')).toHaveCount(0);
  expect(new URL(page.url()).hash).toBe('');
  await page.goto('/#case=unknown');
  await expect(page.locator('[data-case="kyiv-summer-heat"]')).toHaveAttribute('aria-pressed', 'true');
});

test('the URL module parses and writes both link formats', async ({ page }) => {
  await page.goto('/');
  const out = await page.evaluate(async () => {
    const { parseHash, formatHash } = await import('/src/url.ts');
    const spot = { kind: 'spot', variable: 'precip', season: 'DJF', start: 1981, end: 2025, lon: 30.52, lat: 50.45 };
    const month = { ...spot, season: 7 };
    return {
      caseHash: formatHash({ kind: 'case', id: 'kyiv-colder' }),
      caseBack: parseHash(formatHash({ kind: 'case', id: 'kyiv-colder' })),
      spotHash: formatHash(spot),
      spotBack: parseHash(formatHash(spot)),
      monthBack: parseHash(formatHash(month)),
      plain: parseHash('#v=precip&s=JJA&p=1981-2025&pt=-8.125,36.5'),
      invalid: ['', '#v=precip', '#v=precip&s=XYZ&p=1981-2025&pt=1,2', '#v=precip&s=JJA&p=81-25&pt=1,2', '#v=precip&s=JJA&p=1981-2025&pt=1,95', '#v=precip&s=13&p=1981-2025&pt=1,2'].map(parseHash),
      empty: formatHash(null),
    };
  });
  assert.equal(out.caseHash, '#case=kyiv-colder');
  assert.deepEqual(out.caseBack, { kind: 'case', id: 'kyiv-colder' });
  assert.equal(out.spotHash, '#v=precip&s=DJF&p=1981-2025&pt=30.52%2C50.45');
  assert.deepEqual(out.spotBack, { kind: 'spot', variable: 'precip', season: 'DJF', start: 1981, end: 2025, lon: 30.52, lat: 50.45 });
  assert.equal(out.monthBack.season, 7);
  assert.deepEqual(out.plain, { kind: 'spot', variable: 'precip', season: 'JJA', start: 1981, end: 2025, lon: -8.125, lat: 36.5 });
  assert.deepEqual(out.invalid, [null, null, null, null, null, null]);
  assert.equal(out.empty, '');
});

test('live mode loads cases in parallel, opens the first one and keeps a failed case clickable', async ({ page }) => {
  const heat = cases['kyiv-summer-heat'], colder = cases['kyiv-colder'];
  const responses = { 'kyiv-colder': colder, 'kyiv-summer-heat': heat };
  await liveCases(page, ['kyiv-colder', 'kyiv-summer-heat', 'lviv-drier'], responses);
  await page.goto('/?source=live');
  await expect(page.locator('[data-case="kyiv-colder"]')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('.hero .metric-value')).toContainText(fmt(colder.sen.slope_per_decade));
  await expect(page.locator('[data-case="kyiv-summer-heat"] span')).toHaveText('Air temperature · Summer');
  await expect(page.locator('[data-case="lviv-drier"] b')).toHaveText(cases['lviv-drier'].case.claim_text);
  await expect(page.locator('[data-case="lviv-drier"] span')).toHaveCount(0);
  responses['lviv-drier'] = cases['lviv-drier'];
  await page.locator('[data-case="lviv-drier"]').click();
  await expect(page.locator('[data-case="lviv-drier"]')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('.hero').getByRole('heading', { name: 'Not proven', exact: true })).toBeVisible();
});

test('warnings come from backend fields, and source disagreement is reported once', async ({ page }) => {
  const disagree = structuredClone(cases['kyiv-summer-heat']);
  disagree.verdict = 'not_proven'; disagree.reason = 'sources_disagree'; disagree.witness.agreement = 'disagree';
  const robust = structuredClone(cases['kyiv-colder']);
  robust.case.claim_text = 'Not robust test case'; robust.verdict = 'not_proven'; robust.reason = 'not_robust';
  await liveCases(page, ['kyiv-summer-heat', 'kyiv-colder'], { 'kyiv-summer-heat': disagree, 'kyiv-colder': robust });
  await page.goto('/?source=live');
  await expect(page.locator('.hero .warn')).toHaveCount(1);
  await expect(page.locator('.hero .warn')).toHaveText(`The ground station ${disagree.witness.station.name} and the NASA POWER record disagree about this trend.`);
  await page.locator('[data-case="kyiv-colder"]').click();
  await expect(page.locator('.hero .warn')).toHaveText(['The result changes when the first or last years are shifted, so it is not robust.']);
  await expect(page.locator('.hero')).not.toContainText('The evidence does not show a real trend yet.');
});

test('the case grid and hero fit a 390 px screen', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.locator('.hero')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
