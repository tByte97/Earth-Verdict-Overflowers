import { test, expect } from '@playwright/test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const stopped = JSON.parse(await readFile(new URL('../../data/cases/global-warming-stopped.json', import.meta.url), 'utf8'));
const kyiv = JSON.parse(await readFile(new URL('../../data/cases/kyiv-colder.json', import.meta.url), 'utf8'));
const claim = 'потепління зупинилось після 1998';
const parsed = { spec: { ...stopped.case, claim_text: claim }, place_found: true, place_query: null, notes: ['Stopped is checked as not rising: a clear rise refutes it.'], model: 'test' };

async function live(page, parseReply) {
  await page.route('https://gibs.earthdata.nasa.gov/**', route => route.abort());
  await page.route('**/api/cases', route => route.fulfill({ json: [] }));
  await page.route('**/api/variables', route => route.fulfill({ json: [kyiv.variable, stopped.variable] }));
  await page.route('**/api/places?*', route => route.fulfill({ json: [kyiv.case.place] }));
  const parses = [], checks = [];
  await page.route('**/api/parse-claim', route => { parses.push(route.request().postDataJSON()); return route.fulfill(parseReply); });
  await page.route('**/api/check', route => { checks.push(route.request().postDataJSON()); return route.fulfill({ json: { ...stopped, case: route.request().postDataJSON() } }); });
  await page.goto('/?source=live');
  await page.locator('.case-parameters').evaluate(element => { element.open = true; });
  await expect(page.getByRole('combobox', { name: 'Variable', exact: true })).toBeEnabled();
  return { parses, checks };
}

test('a typed claim is read into the fields and checked only after the user confirms them', async ({ page }) => {
  const { parses, checks } = await live(page, { json: parsed });
  await page.getByLabel('Claim', { exact: true }).fill(claim);
  await page.getByRole('button', { name: 'Read claim' }).click();

  await expect(page.getByRole('button', { name: 'Check claim' })).toBeVisible();
  assert.deepEqual(parses, [{ text: claim }]);
  assert.equal(checks.length, 0);                           // reading never runs a check
  await expect(page.getByRole('combobox', { name: 'Variable', exact: true })).toHaveValue('global_temp');
  await expect(page.getByLabel('From')).toHaveValue('1998');
  await expect(page.getByRole('combobox', { name: 'Claim direction' })).toHaveValue('decrease');
  await expect(page.locator('.will-test')).toContainText('temperature of the planet or a continent · The whole planet · whole year · 1998–2025 · is it decreasing?');
  await expect(page.locator('.read-notes')).toContainText('Stopped is checked as not rising');

  await page.getByRole('button', { name: 'Check claim' }).click();
  await expect(page.getByRole('heading', { name: 'Refuted', exact: true })).toBeVisible();
  assert.deepEqual(checks, [parsed.spec]);
});

test('if the claim cannot be read, the user is told to set the fields and the next press checks them', async ({ page }) => {
  const { checks } = await live(page, { status: 503, json: { error: { code: 'llm_unavailable', message: 'Reading claims is not configured on this server.' } } });
  await page.getByLabel('Claim', { exact: true }).fill(claim);
  await page.getByRole('button', { name: 'Read claim' }).click();
  await expect(page.getByRole('alert')).toContainText('Reading claims is not configured on this server. Set the parameters below by hand');
  await page.getByLabel('Place', { exact: true }).fill('Ky');
  await page.getByRole('button', { name: kyiv.case.place.name, exact: true }).click();
  await page.getByRole('button', { name: 'Check claim' }).click();
  await expect.poll(() => checks.length).toBe(1);
});

test('fields set by hand are checked as they are, without reading the claim', async ({ page }) => {
  const { parses, checks } = await live(page, { json: parsed });
  await page.getByLabel('Claim', { exact: true }).fill('My own wording');
  await page.getByLabel('Place', { exact: true }).fill('Ky');
  await page.getByRole('button', { name: kyiv.case.place.name, exact: true }).click();
  await expect(page.locator('.will-test')).toContainText(kyiv.case.place.name);
  await page.getByRole('button', { name: 'Check claim' }).click();
  await expect.poll(() => checks.length).toBe(1);
  assert.equal(parses.length, 0);
});
