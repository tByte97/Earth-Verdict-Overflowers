import heat from '../../data/cases/kyiv-summer-heat.json';
import rain from '../../data/cases/lviv-drier.json';
import snow from '../../data/cases/kyiv-winter-snow.json';
import colder from '../../data/cases/kyiv-colder.json';
import summerRain from '../../data/cases/kyiv-summer-rain.json';
import stopped from '../../data/cases/global-warming-stopped.json';
import type { DemoCase } from './types';
import { parseCheckResult } from './schema';

// Import the team's canonical files directly. Never copy, calculate or rewrite their values.
// The first entry is the case opened on first load in saved mode; live mode follows GET /api/cases.
export const demoCases: DemoCase[] = [
  { id: 'kyiv-summer-heat', label: `Kyiv · Summer heat · ${heat.verdict.replace('_', ' ')}`, result: parseCheckResult(heat) },
  { id: 'lviv-drier', label: `Lviv · Rainfall · ${rain.verdict.replace('_', ' ')}`, result: parseCheckResult(rain) },
  { id: 'kyiv-winter-snow', label: `Kyiv · Winter snow · ${snow.verdict.replace('_', ' ')}`, result: parseCheckResult(snow) },
  { id: 'kyiv-colder', label: `Kyiv · Colder years · ${colder.verdict.replace('_', ' ')}`, result: parseCheckResult(colder) },
  { id: 'kyiv-summer-rain', label: `Kyiv · Summer rain · ${summerRain.verdict.replace('_', ' ')}`, result: parseCheckResult(summerRain) },
  { id: 'global-warming-stopped', label: `Global · Warming stopped · ${stopped.verdict.replace('_', ' ')}`, result: parseCheckResult(stopped) },
];
