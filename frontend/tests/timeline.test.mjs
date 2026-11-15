import { test, expect } from '@playwright/test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const read = async path => JSON.parse(await readFile(new URL(path, import.meta.url), 'utf8'));
const heat = await read('../../data/cases/kyiv-summer-heat.json');
const summer = await read('../../data/layers/years_air_temp_JJA.json');
const trend = await read('../../data/layers/trends_T2M_JJA.geojson');

async function open(page, path = '/') {
  await page.route('https://gibs.earthdata.nasa.gov/**', route => route.abort());
  const errors = [];
  page.on('pageerror', error => errors.push(error.stack || error.message));
  await page.goto(path);
  return errors;
}
const year = (map, y) => map.years.indexOf(y);

test('the timeline puts one year on the globe, in plain words, and returns to the whole-period trend', async ({ page }) => {
  const errors = await open(page);
  await page.locator('[data-case="kyiv-summer-heat"]').click();
  const timeline = page.getByTestId('timeline');
  await expect(timeline).toBeVisible();
  await expect(page.getByTestId('timeline-now')).toHaveText(`${summer.years[0]}–${summer.years.at(-1)}: pick a year or press play`);
  await expect(page.getByTestId('trend-legend')).toBeVisible();
  assert.equal(await timeline.locator('.timeline-bars i').count(), summer.years.length);

  const slider = page.getByRole('slider', { name: 'Year' });
  await slider.focus();
  await page.keyboard.press('ArrowLeft');                               // from the last year to the one before it
  const i = summer.years.length - 2, mean = summer.mean[i];
  await expect(page.getByTestId('timeline-now')).toHaveText(String(summer.years[i]));
  await expect(page.getByTestId('timeline-headline')).toHaveText(`${summer.years[i]}: ${Math.abs(mean).toFixed(1)} °C ${mean > 0 ? 'warmer' : 'cooler'} than usual`);
  await expect(page.locator('.stage-title .src')).toContainText('compared with the 1991–2020 average');
  if (summer.rank[i] === 1) await expect(page.locator('.stage-title .src')).toContainText(`the warmest of ${summer.years.length} summers`);
  // The legend now reads the year, not the trend; the trend's significance dots are gone with it.
  await expect(page.getByTestId('year-legend')).toContainText(`in ${summer.years[i]}`);
  await expect(page.getByTestId('trend-legend')).toHaveCount(0);
  await expect(timeline.locator('.timeline-bars i[data-on]')).toHaveCount(1);

  // The 10-year average starts once ten years exist, and says which years it covers.
  await page.getByLabel('10-year average').check();
  await expect(slider).toHaveAttribute('min', String(summer.window - 1));
  await expect(page.getByTestId('timeline-now')).toHaveText(`${summer.years[i] - summer.window + 1}–${summer.years[i]}`);
  await expect(page.getByTestId('timeline-headline')).toContainText(`${Math.abs(summer.mean_smooth[i]).toFixed(1)} °C`);
  await page.getByLabel('10-year average').uncheck();

  await page.getByRole('button', { name: 'Whole-period trend' }).click();
  await expect(page.getByTestId('timeline-headline')).toHaveCount(0);
  await expect(page.getByTestId('trend-legend')).toBeVisible();
  await expect(page.locator('.stage-title .big')).toHaveText('Where is air temperature changing over Ukraine?');
  assert.deepEqual(errors, []);
});

test('play walks the years from the start and stops at the last one', async ({ page }) => {
  await open(page);
  await page.locator('[data-case="kyiv-summer-heat"]').click();
  await page.getByRole('button', { name: 'Play the years one by one' }).click();
  await expect(page.getByTestId('timeline-now')).toHaveText(String(summer.years[0]));
  await expect(page.getByTestId('timeline-now')).toHaveText(String(summer.years[2]), { timeout: 5_000 });
  await page.getByRole('button', { name: 'Pause the timeline' }).click();
  const paused = await page.getByTestId('timeline-now').textContent();
  await page.waitForTimeout(1_500);
  await expect(page.getByTestId('timeline-now')).toHaveText(paused);
  // From the year before the last, play shows the last year and then stops by itself.
  await page.getByRole('slider', { name: 'Year' }).fill(String(summer.years.length - 2));
  await page.getByRole('button', { name: 'Play the years one by one' }).click();
  await expect(page.getByTestId('timeline-now')).toHaveText(String(summer.years.at(-1)));
  await expect(page.getByRole('button', { name: 'Play the years one by one' })).toBeVisible({ timeout: 5_000 });
});

test('changing the season keeps the picked year and reads the new map', async ({ page }) => {
  await open(page);
  const winter = await read('../../data/layers/years_air_temp_DJF.json');
  await page.locator('[data-case="kyiv-summer-heat"]').click();
  await page.getByRole('slider', { name: 'Year' }).fill(String(year(summer, 2010)));
  await expect(page.getByTestId('timeline-now')).toHaveText('2010');
  await page.getByRole('group', { name: 'Trend map season' }).getByRole('button', { name: 'Winter' }).click();
  const mean = winter.mean[year(winter, 2010)];
  await expect(page.getByTestId('timeline-headline')).toHaveText(`2010: ${Math.abs(mean).toFixed(1)} °C ${mean > 0 ? 'warmer' : 'cooler'} than usual`);
  assert.equal(await page.getByTestId('timeline').locator('.timeline-bars i').count(), winter.years.length);
});

test('live mode reads the year maps from the backend and offers no timeline when there are none', async ({ page }) => {
  await page.route('**/api/cases', route => route.fulfill({ json: [] }));
  await page.route('**/api/variables', route => route.fulfill({ json: [heat.variable] }));
  await page.route('**/api/grid/index', route => route.fulfill({ json: [{ variable_id: 'air_temp', season: 'JJA', start_year: 1981, end_year: 2025, units_per_decade: '°C/decade' }] }));
  await page.route('**/api/grid?*', route => route.fulfill({ json: trend }));
  let built = true;
  const asked = [];
  await page.route('**/api/grid/years?*', route => {
    asked.push(new URL(route.request().url()).search);
    return built ? route.fulfill({ json: summer }) : route.fulfill({ status: 503, json: { error: { code: 'source_unavailable', message: 'This year-by-year map has not been built yet.' } } });
  });
  await open(page, '/?source=live');
  await expect(page.getByTestId('timeline')).toBeVisible();
  assert.deepEqual(asked, ['?variable_id=air_temp&season=JJA']);
  await page.getByRole('slider', { name: 'Year' }).fill(String(year(summer, 1985)));
  await expect(page.getByTestId('timeline-headline')).toContainText('1985: ');

  built = false;
  await page.reload();
  await expect(page.getByTestId('trend-legend')).toBeVisible();
  await expect(page.getByTestId('timeline')).toHaveCount(0);
});
