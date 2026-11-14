import { useEffect, useRef } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import type { CheckResult, Place } from '../types';
import './globe.css';

export type Station = NonNullable<CheckResult['witness']>['station'];
export interface PickedPoint { lat: number; lon: number }

const BLUE_MARBLE = 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_ShadedRelief_Bathymetry/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg';

// The background layer stays visible when tiles fail, so the globe and markers work offline.
const style: maplibregl.StyleSpecification = {
  version: 8,
  projection: { type: 'globe' },
  sources: {
    bluemarble: {
      type: 'raster', tiles: [BLUE_MARBLE], tileSize: 256, maxzoom: 8,
      attribution: 'Imagery: <a href="https://www.earthdata.nasa.gov/gibs" target="_blank" rel="noreferrer">NASA EOSDIS GIBS</a> · Blue Marble',
    },
  },
  layers: [
    { id: 'background', type: 'background', paint: { 'background-color': '#1c3a4a' } },
    { id: 'bluemarble', type: 'raster', source: 'bluemarble' },
  ],
};

const coords = (lat: number, lon: number) => `${Math.abs(lat)}° ${lat >= 0 ? 'N' : 'S'}, ${Math.abs(lon)}° ${lon >= 0 ? 'E' : 'W'}`;

// Tooltip text is set via textContent: names come from data, never as HTML.
function markerElement(kind: 'place' | 'station', lines: string[]) {
  const element = document.createElement('div');
  element.className = `globe-marker globe-marker-${kind}`;
  element.tabIndex = 0;
  element.setAttribute('role', 'img');
  element.setAttribute('aria-label', lines.join(', '));
  const tip = document.createElement('div');
  tip.className = 'globe-tip';
  for (const line of lines) tip.appendChild(document.createElement('div')).textContent = line;
  element.appendChild(tip);
  return element;
}

export function Globe({ place, station, onPick }: { place: Place | null; station: Station | null; onPick?: (point: PickedPoint) => void }) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const pick = useRef(onPick);
  pick.current = onPick;

  useEffect(() => {
    const instance = new maplibregl.Map({ container: container.current!, style, center: [20, 30], zoom: 1.4, attributionControl: { compact: false } });
    instance.on('click', event => { const { lat, lng } = event.lngLat.wrap(); pick.current?.({ lat, lon: lng }); });
    map.current = instance;
    return () => { instance.remove(); map.current = null; };
  }, []);

  useEffect(() => {
    if (!place || !map.current) return;
    const marker = new maplibregl.Marker({ element: markerElement('place', [place.name, coords(place.lat, place.lon)]) })
      .setLngLat([place.lon, place.lat]).addTo(map.current);
    map.current.flyTo({ center: [place.lon, place.lat], zoom: 8.5, essential: true });
    return () => { marker.remove(); };
  }, [place]);

  useEffect(() => {
    if (!station || !map.current) return;
    const marker = new maplibregl.Marker({ element: markerElement('station', [`NOAA station · ${station.name}`, coords(station.lat, station.lon), `${station.distance_km} km from the case point`]) })
      .setLngLat([station.lon, station.lat]).addTo(map.current);
    return () => { marker.remove(); };
  }, [station]);

  return <div className="globe">
    <div ref={container} className="globe-map" />
    {onPick && <p className="globe-hint">Click the globe to pick coordinates</p>}
  </div>;
}
