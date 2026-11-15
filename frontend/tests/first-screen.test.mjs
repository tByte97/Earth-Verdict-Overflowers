import { test, expect } from '@playwright/test';
import { readFile } from 'node:fs/promises';

const heat = JSON.parse(await readFile(new URL('../../data/cases/kyiv-summer-heat.json', import.meta.url), 'utf8'));

test.beforeEach(async ({ page }) => {
  await page.route('https://gibs.earthdata.nasa.gov/**', route => route.abort());
  await page.route('**/api/variables', route => route.fulfill({ json: [heat.variable] }));
  await page.route('**/api/cases', route => route.fulfill({ json: [] }));
});

const place = { place_id: 'om:1', name: 'Bila Tserkva, Ukraine', lat: 49.8, lon: 30.1 };

async function openForm(page) {
  await page.route('**/api/places?*', route => route.fulfill({ json: [place] }));
  await page.goto('/?source=live');
  await expect(page.getByRole('combobox', { name: 'Variable', exact: true })).toBeEnabled();
  await page.locator('.case-parameters').evaluate(element => { element.open = true; });
}

async function fillForm(page) {
  await page.getByLabel('Claim', { exact: true }).fill('Summers are getting hotter');
  await page.getByLabel('Place', { exact: true }).fill('Bila');
  await page.getByRole('button', { name: place.name, exact: true }).click();
}

test('a busy live service falls back to the nearest saved snapshot', async ({ page }) => {
  await page.route('**/api/check', route => route.fulfill({ status: 503, json: { error: { code: 'busy', message: 'The live service is busy.' } } }));
  await openForm(page);
  await fillForm(page);
  await page.getByRole('button', { name: 'Check claim', exact: true }).click();
  await expect(page.locator('.notice')).toContainText('Live service busy — showing a saved NASA snapshot');
  await expect(page.locator('.notice')).toContainText('Kyiv');
  await expect(page.locator('.verdict')).toBeVisible();
  await expect(page.locator('.verdict-card .tag')).toHaveText('Saved backend response');
  await expect(page.getByRole('alert')).toHaveCount(0);
});

test('a real backend error is still reported, not hidden behind a snapshot', async ({ page }) => {
  await page.route('**/api/check', route => route.fulfill({ status: 400, json: { error: { code: 'no_data', message: 'No air temperature data here (open ocean, ice or outside the product\'s coverage).' } } }));
  await openForm(page);
  await fillForm(page);
  await page.getByRole('button', { name: 'Check claim', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('open ocean');
  await expect(page.locator('.notice')).toHaveCount(0);
});

test('the variable definition is shown under the selector', async ({ page }) => {
  await openForm(page);
  await expect(page.getByText(heat.variable.definition, { exact: true })).toBeVisible();
});
