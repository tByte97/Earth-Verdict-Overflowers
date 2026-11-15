import { test, expect } from '@playwright/test';
import { readFile } from 'node:fs/promises';

const heat = JSON.parse(await readFile(new URL('../../data/cases/kyiv-summer-heat.json', import.meta.url), 'utf8'));
const lviv = JSON.parse(await readFile(new URL('../../data/cases/lviv-drier.json', import.meta.url), 'utf8'));
const terms = ['trend', 'anomaly', 'p_value', 'confidence_interval', 'reanalysis', 'period_robustness', 'witness_station'];

// Help is local UI: neither NASA imagery nor a calculation server is needed to explain a word.
test.beforeEach(async ({ page }) => {
  await page.route(/https:\/\/(?:[^/]+\.)?(?:nasa\.gov|earthdata\.nasa\.gov)\//, route => route.abort());
});

test('seven definitions explain the scientific distinctions without changing backend facts', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.goto('/');
  await expect(page.locator('.metric-value')).toContainText(String(heat.sen.slope_per_decade));
  await expect(page.locator('.variable-definition')).toHaveText(heat.variable.definition);
  await page.locator('.word-glossary > summary').click();
  const entries = page.locator('.glossary-body [data-term]');
  expect(await entries.evaluateAll(items => items.map(item => item.dataset.term))).toEqual(terms);
  await expect(page.locator('[data-term="reanalysis"]')).toContainText('not a thermometer reading');
  await expect(page.locator('[data-term="p_value"]')).toContainText('not the chance that the claim is false');
  await expect(page.locator('[data-term="anomaly"]')).toContainText('reference period');
  await expect(page.locator('[data-term="confidence_interval"]')).toContainText('estimated rate of change');
  await expect(page.locator('[data-term="witness_station"]')).toContainText('unavailable');
  await expect(page.locator('.glossary-body')).toContainText('does not tell us how large or important');
  await page.locator('.word-glossary').screenshot({ path: testInfo.outputPath('glossary-desktop.png') });
  await page.locator('.technical > summary').click();
  await page.locator('.raw > summary').click();
  expect(JSON.parse(await page.locator('.raw pre').textContent())).toEqual(heat);
});

test('context help supports keyboard opening, Escape, and all seven terms', async ({ page }, testInfo) => {
  await page.goto('/');
  const trend = page.getByRole('button', { name: 'Explain trend', exact: true });
  await expect(trend).toHaveAttribute('aria-expanded', 'false');
  const helpId = await trend.getAttribute('aria-controls');
  await expect(page.locator(`[id="${helpId}"]`)).toBeHidden();
  await trend.focus(); await page.keyboard.press('Enter');
  await expect(trend).toHaveAttribute('aria-expanded', 'true');
  await expect(page.locator(`[id="${helpId}"]`)).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('trend-help-desktop.png') });
  await page.keyboard.press('Escape');
  await expect(trend).toBeFocused(); await expect(trend).toHaveAttribute('aria-expanded', 'false');
  await page.locator('.technical > summary').click();
  for (const name of ['anomaly', 'p-value', 'confidence interval', 'period robustness', 'witness station']) {
    const control = page.getByRole('button', { name: `Explain ${name}`, exact: true });
    await control.click();
    await expect(page.locator(`[id="${await control.getAttribute('aria-controls')}"]`)).toBeVisible();
    await control.click();
  }
  await page.locator('.sources > summary').click();
  await page.getByRole('button', { name: 'Explain reanalysis', exact: true }).click();
  await expect(page.locator('.sources .term-help-text')).toBeVisible();
  await expect(page.locator('.verdict h3')).toHaveText('Confirmed');
  await expect(page.locator('.metric-value')).toContainText(String(heat.sen.slope_per_decade));
});

test('help fits a phone and preserves the not-proven caveat and missing-station state', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await page.locator('[data-case="lviv-drier"]').click();
  await expect(page.locator('.variable-definition')).toHaveText(lviv.variable.definition);
  await expect(page.locator('.verdict h3')).toHaveText('Not proven');
  await expect(page.getByText('Not enough evidence does not mean no change.', { exact: false })).toBeVisible();
  await expect(page.locator('.witness strong')).toHaveText('No station');
  await page.getByRole('button', { name: 'Explain witness station', exact: true }).click();
  await page.locator('.word-glossary > summary').click();
  await page.locator('.technical > summary').click();
  for (const name of ['p-value', 'confidence interval', 'period robustness']) await page.getByRole('button', { name: `Explain ${name}`, exact: true }).click();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  expect(overflow).toBe(false);
  const outside = await page.locator('.term-help-text:visible').evaluateAll(nodes => nodes.some(node => node.getBoundingClientRect().right > innerWidth));
  expect(outside).toBe(false); expect(errors).toEqual([]);
  await expect(page.locator('.metric-value')).toContainText(String(lviv.sen.slope_per_decade));
  await page.locator('.uncertainty-panel').scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath('not-proven-mobile.png') });
});
