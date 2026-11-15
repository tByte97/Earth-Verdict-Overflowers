import { useEffect, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import type { CheckResult, Place } from '../types';
import { roundCoord, type PickedPoint } from './place';
import { paintGrid, cellAt } from './paint';
import { CellTip, type TrendView } from './TrendMap';
import type { TrendCell } from './trends';
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
type GeoData = Parameters<maplibregl.GeoJSONSource['setData']>[0];
const EMPTY: GeoData = { type: 'FeatureCollection', features: [] };
const BLANK = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=';
const CREAM = '#efe6d2';

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
    // The trend layer is one painted image; dots mark the cells that stay significant after FDR.
    trend: { type: 'image', url: BLANK, coordinates: [[0, 1], [1, 1], [1, 0], [0, 0]] },
    sig: { type: 'geojson', data: EMPTY },
    pair: { type: 'geojson', data: EMPTY },
    pick: { type: 'geojson', data: EMPTY },
  },
  layers: [
    { id: 'background', type: 'background', paint: { 'background-color': '#1c3a4a' } },
    // Muted daytime imagery keeps markers and future data layers in front.
    { id: 'bluemarble', type: 'raster', source: 'bluemarble', paint: { 'raster-saturation': -0.3, 'raster-brightness-max': 0.7 } },
    // Night lights only from far away; they fade out before the map flattens.
    { id: 'blackmarble', type: 'raster', source: 'blackmarble', paint: { 'raster-opacity': byZoom(2.4, 0.8, 3.8, 0) } },
    { id: 'trend', type: 'raster', source: 'trend', paint: { 'raster-opacity': 0.8, 'raster-resampling': 'linear', 'raster-fade-duration': 0 } },
    // Stippling marks significance, the convention of climate trend maps.
    { id: 'sig', type: 'circle', source: 'sig', minzoom: 2.6, paint: {
      'circle-radius': ['interpolate', ['exponential', 2], ['zoom'], 2.6, 0.6, 5, 1.3, 8, 3],
      'circle-color': '#07080b', 'circle-opacity': 0.55, 'circle-pitch-alignment': 'map' } },
    { id: 'coastlines', type: 'raster', source: 'coastlines' },
    { id: 'pair-line', type: 'line', source: 'pair', paint: { 'line-color': CREAM, 'line-width': 1.5, 'line-opacity': 0.8, 'line-dasharray': [2, 2] } },
    { id: 'pick-ring', type: 'circle', source: 'pick', paint: { 'circle-radius': 9, 'circle-color': 'rgba(0,0,0,0)', 'circle-stroke-color': CREAM, 'circle-stroke-width': 2 } },
    { id: 'pick-dot', type: 'circle', source: 'pick', paint: { 'circle-radius': 2.5, 'circle-color': CREAM } },
  ],
};

const ORBIT_ZOOM = 2, LOCAL_ZOOM = 4.75;
const easeIn = (t: number) => t ** 3;
const easeOut = (t: number) => 1 - (1 - t) ** 3;
const easeInOut = (t: number) => (t < 0.5 ? 4 * t ** 3 : 1 - (2 - 2 * t) ** 3 / 2);
const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

// Camera path to a new case: rise to orbit, turn the planet under it, then descend to the local view.
// `stillWanted` turns false when a newer flight, a view button or the user takes over the camera.
async function flyToCase(map: maplibregl.Map, center: [number, number], stillWanted: () => boolean) {
  if (reducedMotion()) { map.jumpTo({ center, zoom: LOCAL_ZOOM }); return; }
  // Listen after starting: easeTo stops the previous animation, whose moveend fires synchronously.
  const leg = (options: maplibregl.EaseToOptions) => new Promise<void>(resolve => {
    map.easeTo({ ...options, essential: true });
    map.once('moveend', () => resolve());
  });
  if (map.getZoom() > ORBIT_ZOOM + 0.4) await leg({ zoom: ORBIT_ZOOM, pitch: 0, bearing: 0, duration: 1100, easing: easeIn });
  if (!stillWanted()) return;
  await leg({ center, zoom: ORBIT_ZOOM, duration: 1000, easing: easeInOut });
  if (!stillWanted()) return;
  await leg({ center, zoom: LOCAL_ZOOM, duration: 1600, easing: easeOut });
}

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

const point = (lon: number, lat: number) => ({ type: 'Feature' as const, properties: {}, geometry: { type: 'Point' as const, coordinates: [lon, lat] } });

function chip(word: string, down: boolean) {
  const element = document.createElement('div');
  element.className = down ? 'lead down' : 'lead';
  element.textContent = word;
  return element;
}

// Draws the layer: painted colour, FDR stipple and, when the backend found one, the opposite pair.
function showTrend(map: maplibregl.Map, view: TrendView | null, fade: boolean): maplibregl.Marker[] {
  map.setLayoutProperty('trend', 'visibility', view ? 'visible' : 'none');
  (map.getSource('sig') as maplibregl.GeoJSONSource).setData(view ? { type: 'FeatureCollection', features: view.cells.filter(cell => cell.significant_fdr).map(cell => point(cell.lon, cell.lat)) } : EMPTY);
  const pair = view?.layer.pair;
  (map.getSource('pair') as maplibregl.GeoJSONSource).setData(pair ? { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: [[pair.a.lon, pair.a.lat], [pair.b.lon, pair.b.lat]] } } : EMPTY);
  if (!view) return [];
  const { grid, lim, pres } = view;
  (map.getSource('trend') as maplibregl.ImageSource).updateImage(paintGrid(grid,
    cell => Math.max(-1, Math.min(1, cell.slope_per_decade / lim)), cell => (!fade || cell.significant_fdr ? 0.88 : 0.3), t => pres.palette((t + 1) / 2)));
  return pair ? [pair.a, pair.b].map(end => new maplibregl.Marker({ element: chip(end.slope_per_decade > 0 ? `▲ ${pres.up}` : `▼ ${pres.down}`, end.slope_per_decade <= 0) })
    .setLngLat([end.lon, end.lat]).addTo(map)) : [];
}

export function Globe({ place, station, onPick, trend = null, fade = true }: { place: Place | null; station: Station | null; onPick?: (point: PickedPoint) => void; trend?: TrendView | null; fade?: boolean }) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const [flying, setFlying] = useState(false);
  const [proj, setProj] = useState(projection(1.4));
  // True once sources can be updated; `ready` also waits for the imagery.
  const [styleReady, setStyleReady] = useState(false);
  const [tip, setTip] = useState<{ cell: TrendCell; x: number; y: number } | null>(null);
  const trendView = useRef(trend);
  trendView.current = trend;
  const activePlace = useRef(place);
  activePlace.current = place;
  const pick = useRef(onPick);
  pick.current = onPick;
  const flight = useRef(0);
  // The place shown on first load is centred by the load handler, not flown to.
  const shownPlace = useRef(place?.place_id);
  // A view button or the user's own gesture takes the camera over from a running flight.
  const takeOver = () => { flight.current++; setFlying(false); };

  useEffect(() => {
    let instance: maplibregl.Map;
    try {
      instance = new maplibregl.Map({ container: container.current!, style, center: [20, 30], zoom: 1.4, attributionControl: { compact: window.matchMedia('(max-width: 640px)').matches },
        // On touch screens one finger scrolls the page; two fingers move the globe.
        cooperativeGestures: window.matchMedia('(pointer: coarse)').matches, maxZoom: 9, maxPitch: 50 });
    } catch {
      setUnavailable(true);
      return;
    }
    instance.touchPitch.disable();
    const resize = new ResizeObserver(() => instance.resize());
    resize.observe(container.current!);
    // Sources can take data once the style is parsed; 'load' waits for the first tiles, which may never arrive offline.
    instance.once('style.load', () => {
      instance.resize();
      // MapLibre opens compact attribution expanded; start collapsed so it stays one icon on phones.
      const attribution = container.current?.querySelector('.maplibregl-compact');
      attribution?.classList.remove('maplibregl-compact-show');
      attribution?.removeAttribute('open');
      if (activePlace.current) instance.setCenter([activePlace.current.lon, activePlace.current.lat]);
      setStyleReady(true);
    });
    instance.once('idle', () => setReady(true));
    instance.on('movestart', event => { if (event.originalEvent) takeOver(); setTip(null); });
    instance.on('zoom', () => setProj(current => { const next = projection(instance.getZoom()); return next.mode === current.mode ? current : next; }));
    // Hover shows the exact values of the cell under the pointer, never the blended colour.
    instance.on('mousemove', event => {
      const view = trendView.current;
      const overMarker = event.originalEvent.target instanceof Element && event.originalEvent.target.closest('.globe-marker');
      const cell = view && !overMarker ? cellAt(view.grid, event.lngLat.wrap().lng, event.lngLat.lat) : undefined;
      setTip(cell ? { cell, x: event.originalEvent.clientX, y: event.originalEvent.clientY } : null);
    });
    instance.getCanvas().addEventListener('mouseleave', () => setTip(null));
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
    // A picked point keeps the camera where the user clicked; a new case flies there.
    if (place.place_id !== shownPlace.current && !place.place_id.startsWith('pt:')) {
      const id = ++flight.current;
      setFlying(!reducedMotion());
      void flyToCase(map.current, [place.lon, place.lat], () => flight.current === id).finally(() => { if (flight.current === id) setFlying(false); });
    }
    shownPlace.current = place.place_id;
  }, [place]);

  // The picked spot is a ring on the map; the station stays a separate marker.
  useEffect(() => {
    if (styleReady) (map.current!.getSource('pick') as maplibregl.GeoJSONSource).setData(place ? point(place.lon, place.lat) : EMPTY);
  }, [styleReady, place]);

  useEffect(() => {
    if (!styleReady) return;
    setTip(null);
    const chips = showTrend(map.current!, trend, fade);
    return () => { for (const marker of chips) marker.remove(); };
  }, [styleReady, trend, fade]);

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
    {!unavailable && <div className="globe-controls">
      <span className="globe-proj" data-mode={proj.mode} aria-live="polite">{proj.label}</span>
      <div className="globe-view-controls" role="group" aria-label="Map view">
        <button type="button" onClick={() => { takeOver(); map.current?.flyTo({ zoom: 1.4, duration: 600 }); }}>Globe view</button>
        {onPick && <button type="button" onClick={() => { const { lat, lng } = map.current!.getCenter().wrap(); onPick(pickPoint(lat, lng)); }}>Use map centre</button>}
        <button type="button" disabled={!place} onClick={() => { takeOver(); if (place) map.current?.flyTo({ center: [place.lon, place.lat], zoom: LOCAL_ZOOM, duration: 600 }); }}>Local view</button>
      </div>
      {onPick && <p className="globe-hint">{ready ? 'Click the map to check a spot' : 'Loading imagery…'}</p>}
    </div>}
    {tip && trend && <CellTip view={trend} {...tip} />}
  </div>;
}
