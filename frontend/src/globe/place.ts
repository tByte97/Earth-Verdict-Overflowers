import type { Place } from '../types';

export interface PickedPoint { lat: number; lon: number }

// Two decimals; a rounded negative zero becomes 0 so ids never read "-0.00".
export const roundCoord = (value: number) => {
  const rounded = Math.round(value * 100) / 100;
  return rounded === 0 ? 0 : rounded;
};

// Place for a point picked on the globe, e.g. pt:50.45,30.52 named "50.45° N, 30.52° E".
// The backend normalises the point to its POWER grid cell.
export function pointPlace({ lat, lon }: PickedPoint): Place {
  const la = roundCoord(lat), lo = roundCoord(lon);
  return {
    place_id: `pt:${la.toFixed(2)},${lo.toFixed(2)}`,
    name: `${Math.abs(la).toFixed(2)}° ${la < 0 ? 'S' : 'N'}, ${Math.abs(lo).toFixed(2)}° ${lo < 0 ? 'W' : 'E'}`,
    lat: la, lon: lo,
  };
}
