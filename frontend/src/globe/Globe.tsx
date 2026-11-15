import { useEffect, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import type { CheckResult, Place } from '../types';
import { roundCoord, type PickedPoint } from './place';
import { GLOBE_VIEW, flyToView, reducedMotion, type Destination } from './camera';
import './globe.css';

export type Station = NonNullable<CheckResult['witness']>['station'];

const pickPoint = (lat: number, lon: number): PickedPoint => ({ lat: roundCoord(lat), lon: roundCoord(lon) });

const BLUE_MARBLE = 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_ShadedRelief_Bathymetry/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg';
// City lights seen from orbit; a fixed composite date keeps the layer stable.
const BLACK_MARBLE = 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/VIIRS_Black_Marble/default/2016-01-01/GoogleMapsCompatible_Level8/{z}/{y}/{x}.png';
// Coastlines only: the GIBS borders layer cuts Crimea off from Ukraine, and its labels use outdated names.
const COASTLINES = 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/Coastlines/default/GoogleMapsCompatible_Level9/{z}/{y}/{x}.png';

// Zoom band in which the globe unrolls into a flat Web Mercator map.
const GLOBE_UNTIL = 3.2, FLAT_FROM = 4.8;
const byZoom = (...stops: (number | string)[]) => ['interpolate', ['linear'], ['zoom'], ...stops] as maplibregl.ExpressionSpecification;

// The background layer stays visible when tiles fail, so the globe and markers work offline.
const style: maplibregl.StyleSpecification = {
  version: 8,
  projection: { type: byZoom(GLOBE_UNTIL, 'vertical-perspective', FLAT_FROM, 'mercator') },
  // The atmosphere glow belongs to the globe; it fades out as the map flattens.
  sky: { 'atmosphere-blend': byZoom(0, 1, GLOBE_UNTIL, 0.7, FLAT_FROM, 0) },
  sources: {
    bluemarble: {
      type: 'raster', tiles: [BLUE_MARBLE], tileSize: 256, maxzoom: 8,
      attribution: 'Imagery: <a href="https://www.earthdata.nasa.gov/gibs" target="_blank" rel="noreferrer">NASA EOSDIS GIBS</a> · Blue Marble, VIIRS Black Marble 2016, coastlines',
    },
    blackmarble: { type: 'raster', tiles: [BLACK_MARBLE], tileSize: 256, maxzoom: 8 },
    coastlines: { type: 'raster', tiles: [COASTLINES], tileSize: 256, maxzoom: 9 },
  },
  layers: [
    { id: 'background', type: 'background', paint: { 'background-color': '#1c3a4a' } },
    // Muted daytime imagery keeps markers and future data layers in front.
    { id: 'bluemarble', type: 'raster', source: 'bluemarble', paint: { 'raster-saturation': -0.3, 'raster-brightness-max': 0.7 } },
    // Night lights only from far away; they fade out before the map flattens.
    { id: 'blackmarble', type: 'raster', source: 'blackmarble', paint: { 'raster-opacity': byZoom(2.4, 0.8, 3.8, 0) } },
    { id: 'coastlines', type: 'raster', source: 'coastlines' },
  ],
};

const LOCAL_ZOOM = 4.75;

// Seeded procedural stars behind the globe: same sky on every load, no image file to fetch.
function starField(seed: number) {
  const size = 1024, canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const g = canvas.getContext('2d');
  if (!g) return '';
  let s = seed;
  const rnd = () => (s = (s * 16807) % 2147483647) / 2147483647;
  for (let i = 0; i < 420; i++) {
    const m = rnd() ** 5, t = rnd();
    g.fillStyle = `rgba(${t < 0.12 ? '205,218,255' : t > 0.92 ? '255,226,190' : '245,245,250'},${0.18 + m * 0.82})`;
    g.beginPath(); g.arc(rnd() * size, rnd() * size, 0.5 + m * 1.4, 0, Math.PI * 2); g.fill();
  }
  return canvas.toDataURL('image/png');
}
let stars: string | undefined;

const projection = (zoom: number) => zoom <= GLOBE_UNTIL ? { mode: 'globe', label: '3D globe' } : zoom >= FLAT_FROM ? { mode: 'flat', label: '2D map · Web Mercator' } : { mode: 'mid', label: 'globe → 2D' };

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

export function Globe({ place, station, destination, onPick }: { place: Place | null; station: Station | null; destination?: Destination | null; onPick?: (point: PickedPoint) => void }) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const [flying, setFlying] = useState(false);
  const [proj, setProj] = useState(projection(1.4));
  const pick = useRef(onPick);
  pick.current = onPick;
  const flight = useRef(0);
  // A view button or the user's own gesture takes the camera over from a running flight.
  const takeOver = () => { flight.current++; setFlying(false); };

  useEffect(() => {
    let instance: maplibregl.Map;
    try {
      instance = new maplibregl.Map({ container: container.current!, style, ...GLOBE_VIEW, attributionControl: { compact: window.matchMedia('(max-width: 640px)').matches },
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
    });
    instance.once('idle', () => setReady(true));
    instance.on('movestart', event => { if (event.originalEvent) takeOver(); });
    instance.on('zoom', () => setProj(current => { const next = projection(instance.getZoom()); return next.mode === current.mode ? current : next; }));
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
    // A picked point's name already is its coordinates.
    const lines = place.place_id.startsWith('pt:') ? [place.name] : [place.name, coords(place.lat, place.lon)];
    const marker = new maplibregl.Marker({ element: markerElement('place', lines) })
      .setLngLat([place.lon, place.lat]).addTo(map.current);
    return () => { marker.remove(); };
  }, [place]);

  // The app asks for a flight with a new destination; a picked point sends none and keeps the camera.
  useEffect(() => {
    if (!destination || !map.current) return;
    const id = ++flight.current;
    setFlying(!reducedMotion());
    void flyToView(map.current, destination.view, () => flight.current === id).finally(() => { if (flight.current === id) setFlying(false); });
  }, [destination]);

  useEffect(() => {
    if (!station || !map.current) return;
    const marker = new maplibregl.Marker({ element: markerElement('station', [`NOAA station · ${station.name}`, coords(station.lat, station.lon), `${station.distance_km} km from the case point`]) })
      .setLngLat([station.lon, station.lat]).addTo(map.current);
    return () => { marker.remove(); };
  }, [station]);

  return <div className="globe" style={{ backgroundImage: `url(${stars ??= starField(11)})` }} data-state={unavailable ? 'unavailable' : ready ? 'ready' : 'loading'} data-flight={flying || undefined} aria-busy={!ready && !unavailable}>
    {unavailable && <div className="map-loading" role="status">The interactive globe is unavailable in this browser. You can still choose a place and inspect every result in the panel.</div>}
    <div ref={container} className="globe-map" />
    <div className="globe-vignette" aria-hidden="true" />
    <div className="flight-title" aria-hidden="true"><small>Case</small><span>{destination?.title}</span></div>
    {!unavailable && <div className="globe-controls">
      <span className="globe-proj" data-mode={proj.mode} aria-live="polite">{proj.label}</span>
      <div className="globe-view-controls" role="group" aria-label="Map view">
        <button type="button" onClick={() => { takeOver(); map.current?.flyTo({ zoom: GLOBE_VIEW.zoom, duration: 600 }); }}>Globe view</button>
        {onPick && <button type="button" onClick={() => { const { lat, lng } = map.current!.getCenter().wrap(); onPick(pickPoint(lat, lng)); }}>Use map centre</button>}
        <button type="button" disabled={!place} onClick={() => { takeOver(); if (place) map.current?.flyTo({ center: [place.lon, place.lat], zoom: LOCAL_ZOOM, duration: 600 }); }}>Local view</button>
      </div>
      {onPick && <p className="globe-hint">{ready ? 'Click the globe to pick coordinates' : 'Loading imagery…'}</p>}
    </div>}
  </div>;
}
