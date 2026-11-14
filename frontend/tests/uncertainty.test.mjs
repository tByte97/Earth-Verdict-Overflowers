import { test, expect } from '@playwright/test';
import { readFile, mkdir } from 'node:fs/promises';

const load = async id => JSON.parse(await readFile(new URL(`../../data/cases/${id}.json`, import.meta.url), 'utf8'));
const heat = await load('kyiv-summer-heat');
const dry = await load('lviv-drier');
const snow = await load('kyiv-winter-snow');

test.beforeEach(async ({ page }) => {
  await page.route('https://gibs.earthdata.nasa.gov/**', route => route.abort());
});

async function liveResult(page, result) {
  await page.route('**/api/variables', route => route.fulfill({ json: [result.variable] }));
  await page.route('**/api/places?*', route => route.fulfill({ json: [result.case.place] }));
  await page.route('**/api/check', route => route.fulfill({ json: result }));
  await page.goto('/?source=live');
  await expect(page.getByRole('combobox', { name: 'Variable', exact: true })).toBeEnabled();
  await page.getByLabel('Claim', { exact: true }).fill('Test-only intercepted case');
  await page.getByLabel('Place', { exact: true }).fill(result.case.place.name.slice(0, 2));
  await page.getByRole('button', { name: result.case.place.name, exact: true }).click();
  await page.getByRole('button', { name: 'Check claim', exact: true }).click();
}

test('not-proven reasons and conditional waiting are visible before opening any details', async ({ page }) => {
  test.setTimeout(60_000);
  const explanations = {
    short_series: 'There are too few observations',
    not_significant: 'not clear enough to distinguish',
    not_robust: 'depends too much on which years',
    sources_disagree: 'disagree about the direction',
  };
  for (const [reason, text] of Object.entries(explanations)) {
    // Synthetic response variants exercise wording; they are never shared case data.
    const result = structuredClone(dry);
    result.reason = reason;
    result.years_to_wait = reason === 'sources_disagree' ? null : 15;
    await liveResult(page, result);
    await expect(page.locator('.verdict')).toContainText(text);
    const panel = page.getByRole('region', { name: 'Why not proven' });
    await expect(panel).toBeVisible();
    await expect(panel).toContainText('Not enough evidence does not mean no change.');
    await expect(panel.getByTestId('visible-wait')).toHaveText(reason === 'sources_disagree' ? 'Not determined' : '15 years');
    await expect(panel).toContainText(reason === 'sources_disagree' ? 'not determined when the sources disagree' : 'not a prediction or a guarantee');
    await expect(page.locator('.technical')).not.toHaveAttribute('open', '');
    await panel.getByRole('button').click();
    await expect(page.locator('.sources').getByRole('heading', { name: 'Detection simulation', exact: true })).toBeVisible();
  }
});

test('keyboard record-length and rate controls preserve the verdict, wait and case period', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Saved case').selectOption('lviv-drier');
  const verdict = await page.locator('.verdict').innerText();
  const wait = await page.getByTestId('visible-wait').innerText();
  await page.locator('.detection-simulator > summary').click();
  const slider = page.getByRole('slider', { name: 'Record through year' });
  await slider.focus();
  await slider.press('Home');
  await expect(slider).toHaveValue(String(dry.case.start_year));
  await expect(page.getByTestId('prefix-p')).toHaveText('Not calculated');
  await expect(page.getByTestId('prefix-count')).toHaveText('1');
  await expect(page.getByTestId('prefix-status')).toContainText('requires 15');
  await slider.press('End');
  await slider.press('ArrowLeft');
  const previous = dry.detection_history.points.at(-2);
  await expect(page.getByTestId('selected-p-point')).toHaveAttribute('data-value', String(previous.p));
  await expect(page.getByTestId('p-threshold')).toHaveAttribute('data-value', '0.05');
  const selectedP = await page.getByTestId('prefix-p').innerText();
  await page.getByRole('region', { name: 'Detection duration' }).getByRole('button', { name: '×2', exact: true }).click();
  await expect(page.getByTestId('prefix-p')).toHaveText(selectedP);
  await expect(slider).toHaveValue(String(previous.end_year));
  await expect(page.locator('.verdict')).toHaveText(verdict, { useInnerText: true });
  await expect(page.getByTestId('visible-wait')).toHaveText(wait);
  await expect(page.getByLabel('From', { exact: true })).toHaveValue(String(dry.case.start_year));
  await expect(page.getByLabel('To', { exact: true })).toHaveValue(String(dry.case.end_year));
  await page.getByRole('button', { name: 'Return to full record' }).click();
  await expect(slider).toHaveValue(String(dry.case.end_year));
  await expect(page.getByTestId('selected-p-point')).toHaveAttribute('data-value', String(dry.detection_history.points.at(-1).p));
  await page.getByLabel('Saved case').selectOption('kyiv-winter-snow');
  await page.locator('.detection-simulator > summary').click();
  await expect(slider).toHaveAttribute('min', String(snow.case.start_year));
  await expect(slider).toHaveValue(String(snow.case.end_year));
  await expect(page.getByTestId('prefix-count')).toHaveText(String(snow.detection.n_years));
  await expect(page.getByRole('region', { name: 'Detection duration' }).getByRole('slider')).toHaveValue('1');
});

test('prefix statistics have exact values, period context and their own one-click method record', async ({ page }) => {
  await page.goto('/');
  await page.locator('.detection-simulator > summary').click();
  await page.locator('.history-values > summary').click();
  const last = heat.detection_history.points.at(-1);
  await expect(page.locator('.history-values tbody tr').last()).toContainText(String(last.p));
  await page.getByRole('button', { name: 'How this period was checked' }).click();
  await expect(page.locator('.sources').getByRole('heading', { name: 'Prefix trend analysis', exact: true })).toBeVisible();
  await page.locator('.technical > summary').click();
  const row = page.locator('.technical .numeric-table tr').filter({ has: page.locator('code', { hasText: /^detection_history\.points\.44\.p$/ }) });
  await expect(row).toContainText(String(last.p));
  await expect(row).toContainText('dimensionless');
  await expect(row).toContainText('1981–2025');
  await expect(row.getByRole('button')).toHaveText('Prefix trend analysis');
});

test('missing observations, rising p-values and genuine zero retain their meanings', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const result = structuredClone(heat);
  result.series[5].value = null;
  result.detection_history.points.forEach((point, i) => {
    if (i >= 5) point.n_observations--;
    if (point.n_observations < 15) { point.p = null; point.correction = null; point.status = 'short_series'; }
  });
  result.detection_history.points[20].p = 0.04;
  result.detection_history.points[21].p = 0.2;
  result.detection_history.points[22].p = 0;
  await liveResult(page, result);
  await page.locator('.detection-simulator > summary').click();
  const slider = page.getByRole('slider', { name: 'Record through year' });
  await slider.press('Home');
  for (let i = 0; i < 20; i++) await slider.press('ArrowRight');
  await expect(page.getByTestId('prefix-count')).toHaveText('20');
  await expect(page.getByTestId('prefix-status')).toContainText('Below 0.05');
  await slider.press('ArrowRight');
  await expect(page.getByTestId('prefix-p')).toHaveText('0.2');
  await expect(page.getByTestId('prefix-status')).toContainText('At or above 0.05');
  await slider.press('ArrowRight');
  await expect(page.getByTestId('prefix-p')).toHaveText('0');
  await expect(page.getByTestId('selected-p-point')).toHaveAttribute('data-value', '0');
  await page.locator('.history-values > summary').click();
  await expect(page.locator('.history-values tbody tr').nth(22).locator('td').nth(1)).toHaveText('0');
  expect(errors).toEqual([]);
});

test('older responses have an honest unavailable state and malformed prefix data is rejected', async ({ page }) => {
  const legacy = structuredClone(heat);
  delete legacy.detection_history;
  await liveResult(page, legacy);
  await page.locator('.detection-simulator > summary').click();
  await expect(page.locator('.history-unavailable')).toContainText('no p-values are inferred');
  await expect(page.getByRole('slider', { name: 'Record through year' })).toHaveCount(0);
  await expect(page.getByRole('region', { name: 'Detection duration' })).toBeVisible();
  // Pydantic serialises a missing history as null: same honest state, and its table row keeps its context.
  const nulled = structuredClone(heat);
  nulled.detection_history = null;
  await liveResult(page, nulled);
  await page.locator('.detection-simulator > summary').click();
  await expect(page.locator('.history-unavailable')).toContainText('no p-values are inferred');
  await page.locator('.technical > summary').click();
  const row = page.locator('.numeric-table tbody tr').filter({ has: page.locator('code', { hasText: /^detection_history$/ }) });
  await expect(row).toContainText('Observed prefix test; not a verdict or forecast');
  await expect(row).toContainText('not supplied by this response');
  const malformed = structuredClone(heat);
  malformed.detection_history.points[20].p = 1.5;
  await liveResult(page, malformed);
  await expect(page.getByRole('alert')).toContainText('Invalid CheckResult response');
  await expect(page.locator('.verdict')).toHaveCount(0);
});

test('uncertainty and the open simulator fit desktop and mobile and produce review evidence', async ({ page }) => {
  await mkdir(new URL('../test-results/', import.meta.url), { recursive: true });
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.goto('/');
  await page.getByLabel('Saved case').selectOption('lviv-drier');
  await expect(page.getByRole('region', { name: 'Why not proven' })).toBeVisible();
  await page.locator('.verdict-card').screenshot({ path: 'test-results/uncertainty-default.png' });
  await page.locator('.detection-simulator > summary').click();
  await page.locator('.verdict-card').screenshot({ path: 'test-results/uncertainty-desktop.png' });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('.history-values > summary').click();
  await page.locator('.verdict-card').screenshot({ path: 'test-results/uncertainty-mobile.png' });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
