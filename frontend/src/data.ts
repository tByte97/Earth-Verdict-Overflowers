import heat from '../../data/cases/kyiv-summer-heat.json';
import rain from '../../data/cases/lviv-drier.json';
import snow from '../../data/cases/kyiv-winter-snow.json';
import type { DemoCase } from './types';

// Import the team's canonical files directly. Never copy, calculate or rewrite their values.
export const demoCases: DemoCase[] = [
  { id: 'kyiv-summer-heat', label: `Kyiv · Summer heat · ${heat.verdict.replace('_', ' ')}`, result: heat },
  { id: 'lviv-drier', label: `Lviv · Rainfall · ${rain.verdict.replace('_', ' ')}`, result: rain },
  { id: 'kyiv-winter-snow', label: `Kyiv · Winter snow · ${snow.verdict.replace('_', ' ')}`, result: snow },
] as DemoCase[];
