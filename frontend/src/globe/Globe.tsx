import { useEffect, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import type { CheckResult, Place } from '../types';
import './globe.css';

export type Station = NonNullable<CheckResult['witness']>['station'];
export interface PickedPoint { lat: number; lon: number }

// NASA POWER is gridded at 0.5° x 0.625°; snapping to 0.25° keeps picked points from creating
// a distinct backend cache key for every pixel while staying within the grid resolution.
const snap = (value: number) => Math.round(value * 4) / 4;
const pickPoint = (lat: number, lon: number): PickedPoint => ({ lat: snap(lat), lon: snap(lon) });

const BLUE_MARBLE = 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_ShadedRelief_Bathymetry/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg';
// Coastlines only: the GIBS borders layer cuts Crimea off from Ukraine, and its labels use outdated names.
const COASTLINES = 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/Coastlines/default/GoogleMapsCompatible_Level9/{z}/{y}/{x}.png';

// The background layer stays visible when tiles fail, so the globe and markers work offline.
const style: maplibregl.StyleSpecification = {
  version: 8,
  projection: { type: 'globe' },
  sources: {
    bluemarble: {
      type: 'raster', tiles: [BLUE_MARBLE], tileSize: 256, maxzoom: 8,
      attribution: 'Imagery: <a href="https://www.earthdata.nasa.gov/gibs" target="_blank" rel="noreferrer">NASA EOSDIS GIBS</a> · Blue Marble, coastlines',
    },
    coastlines: { type: 'raster', tiles: [COASTLINES], tileSize: 256, maxzoom: 9 },
  },
  layers: [
    { id: 'background', type: 'background', paint: { 'background-color': '#1c3a4a' } },
    { id: 'bluemarble', type: 'raster', source: 'bluemarble' },
    { id: 'coastlines', type: 'raster', source: 'coastlines' },
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
  const [ready, setReady] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const activePlace = useRef(place);
  activePlace.current = place;
  const pick = useRef(onPick);
  pick.current = onPick;

  useEffect(() => {
    let instance: maplibregl.Map;
    try {
      instance = new maplibregl.Map({ container: container.current!, style, center: [20, 30], zoom: 1.4, attributionControl: { compact: window.matchMedia('(max-width: 640px)').matches },
        // On touch screens one finger scrolls the page; two fingers move the globe.
        cooperativeGestures: window.matchMedia('(pointer: coarse)').matches });
    } catch {
      setUnavailable(true);
      return;
    }
    const resize = new ResizeObserver(() => instance.resize());
    resize.observe(container.current!);
    instance.once('load', () => {
      instance.resize();
      // MapLibre opens compact attribution expanded; start collapsed so it stays one icon on phones.
      const attribution = container.current?.querySelector('.maplibregl-compact');
      attribution?.classList.remove('maplibregl-compact-show');
      attribution?.removeAttribute('open');
      if (activePlace.current) instance.setCenter([activePlace.current.lon, activePlace.current.lat]);
    });
    instance.once('idle', () => setReady(true));
    instance.addControl(new maplibregl.NavigationControl({ showCompass: true }), 'bottom-right');
    instance.on('click', event => {
      if (event.originalEvent.target instanceof Element && event.originalEvent.target.closest('.globe-marker')) return;
      const { lat, lng } = event.lngLat.wrap(); pick.current?.(pickPoint(lat, lng));
    });
    map.current = instance;
    return () => { resize.disconnect(); instance.remove(); map.current = null; };
  }, []);

  useEffect(() => {
    if (!place || !map.current) return;
    const marker = new maplibregl.Marker({ element: markerElement('place', [place.name, coords(place.lat, place.lon)]) })
      .setLngLat([place.lon, place.lat]).addTo(map.current);
    map.current.flyTo({ center: [place.lon, place.lat], zoom: 1.4, duration: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 900 });
    return () => { marker.remove(); };
  }, [place]);

  useEffect(() => {
    if (!station || !map.current) return;
    const marker = new maplibregl.Marker({ element: markerElement('station', [`NOAA station · ${station.name}`, coords(station.lat, station.lon), `${station.distance_km} km from the case point`]) })
      .setLngLat([station.lon, station.lat]).addTo(map.current);
    return () => { marker.remove(); };
  }, [station]);

  return <div className="globe" data-state={unavailable ? 'unavailable' : ready ? 'ready' : 'loading'} aria-busy={!ready && !unavailable}>
    {unavailable && <div className="map-loading" role="status">The interactive globe is unavailable in this browser. You can still choose a place and inspect every result in the panel.</div>}
    {!unavailable && <div className="globe-view-controls" aria-label="Map view">
      <button type="button" onClick={() => map.current?.flyTo({ zoom: 1.4, duration: 600 })}>Globe view</button>
      {onPick && <button type="button" onClick={() => { const { lat, lng } = map.current!.getCenter().wrap(); onPick(pickPoint(lat, lng)); }}>Use map centre</button>}
      <button type="button" disabled={!place} onClick={() => place && map.current?.flyTo({ center: [place.lon, place.lat], zoom: 4.75, duration: 600 })}>Local view</button>
    </div>}
    <div ref={container} className="globe-map" />
    {onPick && !unavailable && <p className="globe-hint">{ready ? 'Click the globe to pick coordinates' : 'Loading imagery…'}</p>}
  </div>;
}
