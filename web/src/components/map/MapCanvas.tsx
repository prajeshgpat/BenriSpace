"use client";

import "maplibre-gl/dist/maplibre-gl.css";

import {
  AttributionControl,
  Map as MaplibreMap,
  Marker,
  NavigationControl,
  setWorkerUrl,
  type GeoJSONSource,
} from "maplibre-gl";
import { useEffect, useRef, useState } from "react";

import { useLatest } from "@/hooks/useLatest";
import type { AreaGeometry, Bbox } from "@/lib/api/types";
import { BASEMAP_STYLE_URLS } from "@/lib/config";
import { AREA_STYLE, CELL_OPACITY, FILL_COLOR_EXPRESSION } from "@/lib/map/colors";
import { EMPTY_CELLS, type CellFeatureCollection } from "@/lib/map/features";
import { tuneDarkStyle } from "@/lib/map/darkStyle";
import { overlayAnchorId } from "@/lib/map/overlayAnchor";
import { METRO_BBOX, initialMetroView, type MapView } from "@/lib/map/viewport";
import type { ResolvedTheme } from "@/lib/theme";

import styles from "./MapCanvas.module.css";

// See scripts/copy-maplibre-worker.mjs for why the worker is served by us.
setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");

const VIEWPORT_DEBOUNCE_MS = 300;
const FOCUS_ZOOM = 12;
const SOURCE_ID = "cells";
const FILL_LAYER = "cells-fill";
const OUTLINE_LAYER = "cells-outline";
const HIGHLIGHT_CASING_LAYER = "cells-highlight-casing";
const HIGHLIGHT_LAYER = "cells-highlight";
const AREA_SOURCE_ID = "area";
const AREA_FILL_LAYER = "area-fill";
const AREA_CASING_LAYER = "area-outline-casing";
const AREA_LINE_LAYER = "area-outline";

const EMPTY_AREA = { type: "FeatureCollection", features: [] } as never;

function areaData(geometry: AreaGeometry | null) {
  return geometry
    ? ({
        type: "FeatureCollection",
        features: [{ type: "Feature", properties: {}, geometry }],
      } as never)
    : EMPTY_AREA;
}

export interface Viewport {
  /** True when the user moved the map, false for jumps the app made itself. */
  user: boolean;
  bbox: Bbox;
  zoom: number;
  center: { lat: number; lon: number };
}

export interface CellClick {
  geohash: string;
  score: number;
  lat: number;
  lon: number;
}

export interface MarkerSpec {
  id: string;
  rank: number;
  lat: number;
  lon: number;
  label: string;
}

export interface FlyRequest {
  lat: number;
  lon: number;
  /** The map never zooms out to reach the place; defaults to a neighbourhood. */
  zoom?: number;
  /** Changes on every request so the same place can be targeted twice. */
  nonce: number;
}

export interface PinSpec {
  lat: number;
  lon: number;
}

interface MapCanvasProps {
  initialView: MapView | null;
  cells: CellFeatureCollection;
  markers: readonly MarkerSpec[];
  activeMarkerId: string | null;
  highlightGeohash: string | null;
  /** The secondary-road polygon to outline; while shown it replaces the cell highlight. */
  areaGeometry?: AreaGeometry | null;
  theme: ResolvedTheme;
  pin: PinSpec | null;
  flyRequest: FlyRequest | null;
  onViewportChange: (viewport: Viewport) => void;
  onCellClick: (cell: CellClick) => void;
  onMarkerClick: (id: string) => void;
  onUnavailable: () => void;
}

/** Fade-in for the area polygon fill. */
const AREA_FADE_MS = 250;

function prefersReducedMotion(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function readViewport(map: MaplibreMap, user: boolean): Viewport {
  const [[west, south], [east, north]] = map.getBounds().toArray();
  const { lat, lng } = map.getCenter();
  return {
    user,
    bbox: [west, south, east, north],
    zoom: map.getZoom(),
    center: { lat, lon: lng },
  };
}

/**
 * Loads the basemap for a theme. Light uses the stock style untouched; dark is
 * recoloured after fetching (tuneDarkStyle falls back to the stock style on
 * any problem).
 */
function loadBasemap(map: MaplibreMap, theme: ResolvedTheme) {
  map.setStyle(BASEMAP_STYLE_URLS[theme], {
    // diff:false makes MapLibre rebuild the style, which is what fires style.load.
    diff: false,
    ...(theme === "dark"
      ? { transformStyle: (_previous, next) => tuneDarkStyle(next) }
      : {}),
  });
}

function addCellLayers(map: MaplibreMap, theme: ResolvedTheme) {
  // Under the basemap's labels, so place names stay readable over the colors.
  const firstLabel = { id: overlayAnchorId(map.getStyle().layers, theme) };

  map.addSource(SOURCE_ID, { type: "geojson", data: EMPTY_CELLS });
  map.addLayer(
    {
      id: FILL_LAYER,
      type: "fill",
      source: SOURCE_ID,
      paint: {
        "fill-color": FILL_COLOR_EXPRESSION as never,
        "fill-opacity": CELL_OPACITY[theme],
        // Adjacent cells would otherwise show hairline seams.
        "fill-antialias": false,
      },
    },
    firstLabel?.id,
  );
  // Cell edges only once cells are big enough on screen to read as a grid.
  map.addLayer(
    {
      id: OUTLINE_LAYER,
      type: "line",
      source: SOURCE_ID,
      minzoom: 11,
      paint: {
        "line-color": "#ffffff",
        "line-opacity": 0.35,
        "line-width": 0.5,
      },
    },
    firstLabel?.id,
  );
  const none = ["==", ["get", "geohash"], ""] as never;
  map.addLayer({
    id: HIGHLIGHT_CASING_LAYER,
    type: "line",
    source: SOURCE_ID,
    filter: none,
    paint: { "line-color": "#111111", "line-width": 5 },
  });
  map.addLayer({
    id: HIGHLIGHT_LAYER,
    type: "line",
    source: SOURCE_ID,
    filter: none,
    paint: { "line-color": "#ffffff", "line-width": 2.5 },
  });
}

function addAreaLayers(map: MaplibreMap, theme: ResolvedTheme, visible: boolean) {
  const firstLabel = { id: overlayAnchorId(map.getStyle().layers, theme) };
  const style = AREA_STYLE[theme];

  map.addSource(AREA_SOURCE_ID, { type: "geojson", data: EMPTY_AREA });
  map.addLayer(
    {
      id: AREA_FILL_LAYER,
      type: "fill",
      source: AREA_SOURCE_ID,
      paint: {
        "fill-color": style.line,
        // Transparent until an area exists; the area effect raises it to fade in.
        "fill-opacity": visible ? style.fillOpacity : 0,
        "fill-opacity-transition": {
          duration: prefersReducedMotion() ? 0 : AREA_FADE_MS,
          delay: 0,
        },
      },
    },
    firstLabel?.id,
  );
  map.addLayer(
    {
      id: AREA_CASING_LAYER,
      type: "line",
      source: AREA_SOURCE_ID,
      layout: { "line-join": "round" },
      paint: { "line-color": style.casing, "line-width": 5, "line-opacity": 0.9 },
    },
    firstLabel?.id,
  );
  map.addLayer(
    {
      id: AREA_LINE_LAYER,
      type: "line",
      source: AREA_SOURCE_ID,
      layout: { "line-join": "round" },
      paint: { "line-color": style.line, "line-width": 2.5 },
    },
    firstLabel?.id,
  );
}

export function MapCanvas({
  initialView,
  cells,
  markers,
  activeMarkerId,
  highlightGeohash,
  areaGeometry = null,
  theme,
  pin,
  flyRequest,
  onViewportChange,
  onCellClick,
  onMarkerClick,
  onUnavailable,
}: MapCanvasProps) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MaplibreMap | null>(null);
  const [ready, setReady] = useState(false);

  const callbacks = useLatest({
    onViewportChange,
    onCellClick,
    onMarkerClick,
    onUnavailable,
  });
  const initial = useRef(initialView);
  // The overlay is re-added after every basemap swap, so it reads the newest
  // data and theme from refs instead of capturing the first render's.
  const latest = useLatest({
    cells,
    highlightGeohash: areaGeometry ? null : highlightGeohash,
    areaGeometry,
    theme,
  });
  const styleTheme = useRef(theme);

  useEffect(() => {
    const element = container.current;
    if (!element) return;

    let map: MaplibreMap;
    try {
      const start = initial.current;
      map = new MaplibreMap({
        container: element,
        // A dark start is loaded right after construction, to be recoloured.
        ...(styleTheme.current === "light"
          ? { style: BASEMAP_STYLE_URLS.light }
          : {}),
        ...(start
          ? { center: [start.lon, start.lat], zoom: start.zoom }
          : {
              bounds: [
                [METRO_BBOX[0], METRO_BBOX[1]],
                [METRO_BBOX[2], METRO_BBOX[3]],
              ],
              fitBoundsOptions: { padding: 12 },
            }),
        attributionControl: false,
        dragRotate: false,
        pitchWithRotate: false,
        maxPitch: 0,
        cooperativeGestures: false,
      });
    } catch {
      // Raised when WebGL is unavailable.
      callbacks.current.onUnavailable();
      return;
    }
    mapRef.current = map;
    if (!initial.current) {
      // The bounds fit shows the whole metro; open four levels closer on the city.
      try {
        const { lat, lon, zoom } = initialMetroView(map.getZoom());
        map.jumpTo({ center: [lon, lat], zoom });
      } catch {
        // Keep the fitted view.
      }
    }
    if (styleTheme.current === "dark") loadBasemap(map, "dark");
    map.touchZoomRotate.disableRotation();
    map.keyboard.disableRotation();
    map.addControl(new NavigationControl({ showCompass: false }), "top-right");
    // Always expanded: the OpenStreetMap credit has to stay visible.
    map.addControl(new AttributionControl({ compact: false }), "bottom-right");

    let timer: ReturnType<typeof setTimeout> | undefined;
    let userMoved = false;
    map.on("moveend", (event) => {
      // Gestures, buttons and keys carry the DOM event; flyTo/jumpTo do not.
      userMoved ||= Boolean(event.originalEvent);
      clearTimeout(timer);
      timer = setTimeout(() => {
        callbacks.current.onViewportChange(readViewport(map, userMoved));
        userMoved = false;
      }, VIEWPORT_DEBOUNCE_MS);
    });

    // Fires for the first style and again after every setStyle: a new basemap
    // arrives without our layers, so they are put back on top of it.
    map.on("style.load", () => {
      addCellLayers(map, styleTheme.current);
      addAreaLayers(map, styleTheme.current, Boolean(latest.current.areaGeometry));
      (map.getSource(AREA_SOURCE_ID) as GeoJSONSource).setData(
        areaData(latest.current.areaGeometry),
      );
      (map.getSource(SOURCE_ID) as GeoJSONSource).setData(latest.current.cells);
      const filter = [
        "==",
        ["get", "geohash"],
        latest.current.highlightGeohash ?? "",
      ] as never;
      map.setFilter(HIGHLIGHT_CASING_LAYER, filter);
      map.setFilter(HIGHLIGHT_LAYER, filter);
    });

    map.on("load", () => {
      map.on("click", FILL_LAYER, (event) => {
        const feature = event.features?.[0];
        if (!feature) return;
        callbacks.current.onCellClick({
          geohash: String(feature.properties.geohash),
          score: Number(feature.properties.score),
          lat: event.lngLat.lat,
          lon: event.lngLat.lng,
        });
      });
      map.on("mouseenter", FILL_LAYER, () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", FILL_LAYER, () => {
        map.getCanvas().style.cursor = "";
      });
      callbacks.current.onViewportChange(readViewport(map, false));
      setReady(true);
    });

    return () => {
      clearTimeout(timer);
      setReady(false);
      map.remove();
      mapRef.current = null;
    };
  }, [callbacks, latest]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || styleTheme.current === theme) return;
    styleTheme.current = theme;
    loadBasemap(map, theme);
  }, [theme, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    (map.getSource(SOURCE_ID) as GeoJSONSource | undefined)?.setData(cells);
  }, [cells, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    // The polygon replaces the rectangle while it is shown.
    const shown = areaGeometry ? null : highlightGeohash;
    const filter = ["==", ["get", "geohash"], shown ?? ""] as never;
    map.setFilter(HIGHLIGHT_CASING_LAYER, filter);
    map.setFilter(HIGHLIGHT_LAYER, filter);
  }, [highlightGeohash, areaGeometry, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    (map.getSource(AREA_SOURCE_ID) as GeoJSONSource | undefined)?.setData(
      areaData(areaGeometry),
    );
    if (map.getLayer(AREA_FILL_LAYER)) {
      map.setPaintProperty(
        AREA_FILL_LAYER,
        "fill-opacity",
        areaGeometry ? AREA_STYLE[latest.current.theme].fillOpacity : 0,
      );
    }
  }, [areaGeometry, ready, latest]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !flyRequest) return;
    const target = {
      center: [flyRequest.lon, flyRequest.lat] as [number, number],
      zoom: Math.max(map.getZoom(), flyRequest.zoom ?? FOCUS_ZOOM),
    };
    // Motion is a courtesy, not information: skip it when asked to.
    if (prefersReducedMotion()) map.jumpTo(target);
    else map.flyTo({ ...target, essential: false });
  }, [flyRequest]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const created = markers.map((spec) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = styles.marker;
      button.textContent = String(spec.rank);
      button.setAttribute("aria-label", spec.label);
      button.dataset.markerId = spec.id;
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        callbacks.current.onMarkerClick(spec.id);
      });
      return new Marker({ element: button })
        .setLngLat([spec.lon, spec.lat])
        .addTo(map);
    });
    return () => created.forEach((marker) => marker.remove());
  }, [callbacks, markers, ready]);

  useEffect(() => {
    const active = activeMarkerId;
    const buttons =
      container.current?.querySelectorAll<HTMLElement>("[data-marker-id]");
    buttons?.forEach((button) => {
      if (button.dataset.markerId === active) button.dataset.active = "true";
      else delete button.dataset.active;
    });
  }, [activeMarkerId, markers, ready]);

  const pinLat = pin?.lat;
  const pinLon = pin?.lon;
  useEffect(() => {
    const map = mapRef.current;
    if (!map || pinLat === undefined || pinLon === undefined) return;
    // MapLibre owns the element's transform, so the drawn pin is a child.
    const element = document.createElement("div");
    element.className = styles.pinAnchor;
    element.setAttribute("aria-hidden", "true");
    element.appendChild(document.createElement("div")).className = styles.pin;
    const marker = new Marker({ element, anchor: "bottom" })
      .setLngLat([pinLon, pinLat])
      .addTo(map);
    return () => {
      marker.remove();
    };
  }, [pinLat, pinLon, ready]);

  return (
    <div className={styles.wrapper}>
      <div ref={container} className={styles.map} />
    </div>
  );
}
