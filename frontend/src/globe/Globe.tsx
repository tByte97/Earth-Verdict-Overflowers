import { useEffect, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import type { CaseSpec, CheckResult, Place } from '../types';
import { roundCoord, type PickedPoint } from './place';
import { loadTrendLayer, type TrendCell, type TrendLayer } from './trends';
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

// Diverging colours with white at zero: warming red / cooling blue, wetter teal / drier brown.
const TREND_COLOURS: Record<string, [string, string]> = { T2M: ['#2166ac', '#b2182b'], PRECTOTCORR: ['#8c510a', '#01665e'] };
const SEASON_NAMES: Record<string, string> = { year: 'whole year', JJA: 'June–August', DJF: 'December–February' };

function showTrendLayer(map: maplibregl.Map, layer: TrendLayer | null) {
  for (const id of ['trend-fill', 'trend-dots']) if (map.getLayer(id)) map.removeLayer(id);
  for (const id of ['trend-cells', 'trend-significant']) if (map.getSource(id)) map.removeSource(id);
  if (!layer) return;
  const extent = Math.max(...layer.features.map(cell => Math.abs(cell.properties.slope_per_decade))) || 1;
  const [negative, positive] = TREND_COLOURS[layer.param] ?? TREND_COLOURS.T2M;
  map.addSource('trend-cells', { type: 'geojson', data: layer as maplibregl.GeoJSONSourceSpecification['data'] });
  // Dots sit at the cell centres given in the layer, only for cells that survive the FDR correction.
  map.addSource('trend-significant', { type: 'geojson', data: { type: 'FeatureCollection', features: layer.features
    .filter(cell => cell.properties.significant_fdr)
    .map(cell => ({ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [cell.properties.lon, cell.properties.lat] } })) } });
  map.addLayer({ id: 'trend-fill', type: 'fill', source: 'trend-cells', paint: {
    'fill-color': ['interpolate', ['linear'], ['get', 'slope_per_decade'], -extent, negative, 0, '#f7f7f7', extent, positive],
    // Light enough for the imagery and coastline to read through; no antialiased edge, so no cell outlines.
    'fill-opacity': ['case', ['get', 'significant_fdr'], 0.6, 0.15],
    'fill-antialias': false,
  } }, 'coastlines');
  map.addLayer({ id: 'trend-dots', type: 'circle', source: 'trend-significant', paint: {
    'circle-radius': byZoom(1.4, 0.7, 5, 1.4),
    'circle-color': '#14202a', 'circle-opacity': 0.7,
  } }, 'coastlines');
}

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

// Values are printed exactly as the layer file gives them.
function cellTip(cell: TrendCell, layer: TrendLayer) {
  const tip = document.createElement('div');
  const lines = [`Trend: ${cell.slope_per_decade} ${layer.units_per_decade}`, `p = ${cell.p}`,
    `${cell.significant_fdr ? 'Significant' : 'Not significant'} after FDR correction (q = ${layer.q})`,
    `Cell centre ${coords(cell.lat, cell.lon)}`];
  for (const line of lines) tip.appendChild(document.createElement('div')).textContent = line;
  return tip;
}

function TrendLegend({ layer }: { layer: TrendLayer }) {
  const slopes = layer.features.map(cell => cell.properties.slope_per_decade);
  const extent = Math.max(...slopes.map(Math.abs));
  const [negative, positive] = TREND_COLOURS[layer.param] ?? TREND_COLOURS.T2M;
  // Open on wide screens; on phones it starts as one line so the map stays visible.
  return <details className="trend-legend" open={!window.matchMedia('(max-width: 640px)').matches}>
    <summary>Trend per decade · {SEASON_NAMES[layer.season] ?? layer.season}</summary>
    <i className="trend-scale" style={{ background: `linear-gradient(90deg, ${negative}, #f7f7f7, ${positive})` }} />
    <span className="trend-ends"><span>−{extent}</span><span>0</span><span>+{extent}</span></span>
    <span>{layer.units_per_decade}; cells range from {Math.min(...slopes)} to {Math.max(...slopes)}</span>
    <span>{layer.start_year && layer.end_year ? `Period ${layer.start_year}–${layer.end_year}` : 'Period not stated in the layer'}</span>
    <span><i className="trend-dot" />Bright with a dot: significant after FDR correction (q = {layer.q}). Pale: not significant.</span>
  </details>;
}

export function Globe({ place, station, variableId, season, onPick }: { place: Place | null; station: Station | null; variableId?: string; season?: CaseSpec['season']; onPick?: (point: PickedPoint) => void }) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const activePlace = useRef(place);
  activePlace.current = place;
  const pick = useRef(onPick);
  pick.current = onPick;
  const flight = useRef(0);
  // The place shown on first load is centred by the load handler, not flown to.
  const shownPlace = useRef(place?.place_id);
  const [trendLayer, setTrendLayer] = useState<TrendLayer | null>(null);
  const trend = useRef(trendLayer);
  trend.current = trendLayer;
  const cellPopup = useRef<maplibregl.Popup | null>(null);

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
    instance.on('movestart', event => { if (event.originalEvent) flight.current++; });
    instance.addControl(new maplibregl.NavigationControl({ showCompass: true }), 'bottom-right');
    // One tip for trend cells: it follows the pointer on hover and stays pinned after a click or tap,
    // when the new place marker lands under the pointer and the map reports a mouseleave.
    const tip = cellPopup.current = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 12, maxWidth: '260px', className: 'globe-cell-tip' });
    let pinned = false;
    const showCell = (event: maplibregl.MapMouseEvent, pin: boolean) => {
      pinned = pin;
      const [cell] = trend.current && instance.getLayer('trend-fill') ? instance.queryRenderedFeatures(event.point, { layers: ['trend-fill'] }) : [];
      if (!cell || !trend.current) { tip.remove(); return; }
      tip.setLngLat(event.lngLat).setDOMContent(cellTip(cell.properties as TrendCell, trend.current)).addTo(instance);
    };
    instance.on('mousemove', 'trend-fill', event => showCell(event, false));
    instance.on('mouseleave', 'trend-fill', () => { if (!pinned) tip.remove(); });
    instance.on('click', event => {
      if (event.originalEvent.target instanceof Element && event.originalEvent.target.closest('.globe-marker')) return;
      showCell(event, true);
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
    // A picked point keeps the camera where the user clicked; a new case flies there.
    if (place.place_id !== shownPlace.current && !place.place_id.startsWith('pt:')) {
      const id = ++flight.current;
      void flyToCase(map.current, [place.lon, place.lat], () => flight.current === id);
    }
    shownPlace.current = place.place_id;
    return () => { marker.remove(); };
  }, [place]);

  useEffect(() => {
    if (!variableId || !season) { setTrendLayer(null); return; }
    const controller = new AbortController();
    loadTrendLayer(variableId, season, controller.signal)
      .then(layer => { if (!controller.signal.aborted) setTrendLayer(layer); })
      .catch(() => { if (!controller.signal.aborted) setTrendLayer(null); });
    return () => controller.abort();
  }, [variableId, season]);

  useEffect(() => {
    cellPopup.current?.remove();
    if (ready && map.current) showTrendLayer(map.current, trendLayer);
  }, [ready, trendLayer]);

  useEffect(() => {
    if (!station || !map.current) return;
    const marker = new maplibregl.Marker({ element: markerElement('station', [`NOAA station · ${station.name}`, coords(station.lat, station.lon), `${station.distance_km} km from the case point`]) })
      .setLngLat([station.lon, station.lat]).addTo(map.current);
    return () => { marker.remove(); };
  }, [station]);

  return <div className="globe" data-state={unavailable ? 'unavailable' : ready ? 'ready' : 'loading'} aria-busy={!ready && !unavailable}>
    {unavailable && <div className="map-loading" role="status">The interactive globe is unavailable in this browser. You can still choose a place and inspect every result in the panel.</div>}
    {!unavailable && <div className="globe-view-controls" aria-label="Map view">
      <button type="button" onClick={() => { flight.current++; map.current?.flyTo({ zoom: 1.4, duration: 600 }); }}>Globe view</button>
      {onPick && <button type="button" onClick={() => { const { lat, lng } = map.current!.getCenter().wrap(); onPick(pickPoint(lat, lng)); }}>Use map centre</button>}
      <button type="button" disabled={!place} onClick={() => { flight.current++; if (place) map.current?.flyTo({ center: [place.lon, place.lat], zoom: LOCAL_ZOOM, duration: 600 }); }}>Local view</button>
    </div>}
    <div ref={container} className="globe-map" />
    {trendLayer && !unavailable && <TrendLegend layer={trendLayer} />}
    {onPick && !unavailable && <p className="globe-hint">{ready ? 'Click the globe to pick coordinates' : 'Loading imagery…'}</p>}
  </div>;
}
