import heat from '../../data/cases/kyiv-summer-heat.json';
import rain from '../../data/cases/lviv-drier.json';
import snow from '../../data/cases/kyiv-winter-snow.json';
import type { DemoCase } from './types';

// Import the team's canonical files directly. Never copy, calculate or rewrite their values.
export const demoCases: DemoCase[] = [
  { id: 'kyiv-summer-heat', label: 'Kyiv · Summer heat · Confirmed', result: heat },
  { id: 'lviv-drier', label: 'Lviv · Rainfall · Refuted', result: rain },
  { id: 'kyiv-winter-snow', label: 'Kyiv · Winter snow · Not proven', result: snow },
] as DemoCase[];
