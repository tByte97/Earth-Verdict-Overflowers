import { expect, test } from '@playwright/test';
import assert from 'node:assert/strict';

test.beforeEach(async ({ page }) => {
  await page.route('https://gibs.earthdata.nasa.gov/**', route => route.abort());
});

test('the panel explains how the detective decides with the same text for every case', async ({ page }) => {
  await page.goto('/?source=saved#case=kyiv-summer-heat');
  const method = page.getByTestId('method');
  await expect(method.getByRole('heading', { name: 'How the detective decides' })).toBeVisible();
  const steps = await page.evaluate(async () => (await import('/src/method/text.ts')).methodSteps.map(step => step.id));
  await expect(method.locator('[data-method]')).toHaveCount(steps.length);
  assert.deepEqual(await method.locator('[data-method]').evaluateAll(els => els.map(el => el.dataset.method)), steps);
  const text = await method.innerText();
  await page.locator('[data-case="lviv-drier"]').click();
  await expect(page.locator('[data-case="lviv-drier"]')).toHaveAttribute('aria-pressed', 'true');
  assert.equal(await page.getByTestId('method').innerText(), text);
});
