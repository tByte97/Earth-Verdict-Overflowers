import { test } from '@playwright/test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const load = async id => JSON.parse(await readFile(new URL(`../../data/cases/${id}.json`, import.meta.url), 'utf8'));
const heat = await load('kyiv-summer-heat');
const dry = await load('lviv-drier');

test.beforeEach(async ({ page }) => {
  await page.route('https://gibs.earthdata.nasa.gov/**', route => route.abort());
  await page.goto('/');
});

// Builds the CSV with the app's own module, served by the dev server.
const csvOf = (page, result) => page.evaluate(async r => {
  const m = await import('/src/csv.ts');
  return { text: m.caseCsv(r), name: m.caseCsvName(r) };
}, result);

// Minimal RFC 4180 reader for the assertions.
function parse(text) {
  const rows = [];
  let row = [], field = '', quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') { field += '"'; i++; }
      else if (c === '"') quoted = false;
      else field += c;
    } else if (c === '"') quoted = true;
    else if (c === ',') { row.push(field); field = ''; }
    else if (c === '\r' && text[i + 1] === '\n') { row.push(field); rows.push(row); row = []; field = ''; i++; }
    else field += c;
  }
  return rows;
}
const show = value => value === null || value === undefined ? '' : String(value);

function split(text) {
  const rows = parse(text);
  const gap = rows.findIndex(r => r.length === 1 && r[0] === '');
  return { fields: Object.fromEntries(rows.slice(1, gap).map(([k, v, u]) => [k, [v, u]])), table: rows.slice(gap + 1) };
}

test('CSV header rows copy slope, interval, p, correction and sources from the result', async ({ page }) => {
  const { text, name } = await csvOf(page, heat);
  assert.equal(name, 'earth-verdict-city-kyiv-air_temp-JJA-1981-2025.csv');
  const { fields } = split(text);
  assert.deepEqual(fields['sen.slope_per_decade'], [String(heat.sen.slope_per_decade), '°C / decade']);
  assert.deepEqual(fields['sen.ci_low'], [String(heat.sen.ci_low), '°C / decade']);
  assert.deepEqual(fields['sen.ci_high'], [String(heat.sen.ci_high), '°C / decade']);
  assert.deepEqual(fields['mk.p'], [String(heat.mk.p), 'dimensionless']);
  assert.equal(fields['mk.correction'][0], heat.mk.correction);
  assert.equal(fields['verdict'][0], heat.verdict);
  assert.equal(fields['baseline.mean'][0], String(heat.baseline.mean));
  assert.equal(fields['witness.station.name'][0], heat.witness.station.name);
  heat.provenance.forEach((source, i) => {
    assert.equal(fields[`provenance.${i}.source`][0], source.source);
    assert.equal(fields[`provenance.${i}.url`][0], source.url);
  });
});

test('CSV table: series, trend line from sen.band and station, with gaps as empty cells', async ({ page }) => {
  const { text } = await csvOf(page, heat);
  const { table } = split(text);
  assert.deepEqual(table[0], ['year', 'series.value (°C)', 'sen.band.mid (°C)', 'sen.band.low (°C)', 'sen.band.high (°C)', 'witness.series.value (°C)']);
  const band = new Map(heat.sen.band.map(p => [p.year, p]));
  const station = new Map(heat.witness.series.map(p => [p.year, p.value]));
  assert.deepEqual(table.slice(1), heat.series.map(p => {
    const b = band.get(p.year);
    return [String(p.year), show(p.value), show(b?.mid), show(b?.low), show(b?.high), show(station.get(p.year))];
  }));
  // Station gaps are empty, never zero.
  assert.equal(table.find(r => r[0] === '2008')[5], '');
});

test('no station: empty station cells and fields, not zero', async ({ page }) => {
  const { text } = await csvOf(page, dry);
  const { fields, table } = split(text);
  assert.equal(fields['witness.station.name'][0], '');
  assert.equal(fields['witness.station.distance_km'][0], '');
  assert.ok(table.slice(1).every(r => r[5] === ''));
});

test('text with commas, quotes and formula characters is quoted and defused', async ({ page }) => {
  // Test-only variant; never shared case data.
  const r = structuredClone(heat);
  r.case.claim_text = '=HYPERLINK("x"), "hotter", yes';
  const { text } = await csvOf(page, r);
  const { fields } = split(text);
  assert.equal(fields['case.claim_text'][0], `'=HYPERLINK("x"), "hotter", yes`);
});
