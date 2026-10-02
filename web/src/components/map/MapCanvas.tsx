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
import type { Bbox } from "@/lib/api/types";
import { BASEMAP_STYLE_URL } from "@/lib/config";
import { CELL_OPACITY, FILL_COLOR_EXPRESSION } from "@/lib/map/colors";
import { EMPTY_CELLS, type CellFeatureCollection } from "@/lib/map/features";
import { METRO_BBOX, type MapView } from "@/lib/map/viewport";

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
  pin: PinSpec | null;
  flyRequest: FlyRequest | null;
  onViewportChange: (viewport: Viewport) => void;
  onCellClick: (cell: CellClick) => void;
  onMarkerClick: (id: string) => void;
  onUnavailable: () => void;
}

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

function addCellLayers(map: MaplibreMap) {
  // Under the basemap's labels, so place names stay readable over the colors.
  const firstLabel = map
    .getStyle()
    .layers.find((layer) => layer.type === "symbol");

  map.addSource(SOURCE_ID, { type: "geojson", data: EMPTY_CELLS });
  map.addLayer(
    {
      id: FILL_LAYER,
      type: "fill",
      source: SOURCE_ID,
      paint: {
        "fill-color": FILL_COLOR_EXPRESSION as never,
        "fill-opacity": CELL_OPACITY,
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

export function MapCanvas({
  initialView,
  cells,
  markers,
  activeMarkerId,
  highlightGeohash,
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

  useEffect(() => {
    const element = container.current;
    if (!element) return;

    let map: MaplibreMap;
    try {
      const start = initial.current;
      map = new MaplibreMap({
        container: element,
        // One light basemap in both themes: the cell colors are tuned to read over it.
        style: BASEMAP_STYLE_URL,
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

    map.on("load", () => {
      addCellLayers(map);
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
  }, [callbacks]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    (map.getSource(SOURCE_ID) as GeoJSONSource | undefined)?.setData(cells);
  }, [cells, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const filter = ["==", ["get", "geohash"], highlightGeohash ?? ""] as never;
    map.setFilter(HIGHLIGHT_CASING_LAYER, filter);
    map.setFilter(HIGHLIGHT_LAYER, filter);
  }, [highlightGeohash, ready]);

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
