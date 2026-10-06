"use client";

import { Marker, type GeoJSONSource, type Map as MaplibreMap } from "maplibre-gl";
import { useEffect, type RefObject } from "react";

import { useLatest } from "@/hooks/useLatest";
import type { TripOverlay } from "@/hooks/useTripPlanner";
import { TRI_STYLE } from "@/lib/map/colors";
import { overlayAnchorId } from "@/lib/map/overlayAnchor";
import type { ResolvedTheme } from "@/lib/theme";

const SOURCE = "tri-areas";
const MAX_ANCHORS = 3;
/** The `idx` of the combined overlap feature; anchors use 0, 1 and 2. */
const OVERLAP_IDX = -1;

const anchorLayer = (i: number, part: "fill" | "casing" | "line") => `tri-anchor-${i}-${part}`;
const OVERLAP_FILL = "tri-overlap-fill";
const OVERLAP_CASING = "tri-overlap-casing";
const OVERLAP_LINE = "tri-overlap-line";

const ALL_LAYERS = [
  ...Array.from({ length: MAX_ANCHORS }, (_, i) => [
    anchorLayer(i, "line"),
    anchorLayer(i, "casing"),
    anchorLayer(i, "fill"),
  ]).flat(),
  OVERLAP_LINE,
  OVERLAP_CASING,
  OVERLAP_FILL,
];

const PIN_LABELS = ["★", "1", "2"];

type Geometry = NonNullable<TripOverlay["combined"]>;

const EMPTY = { type: "FeatureCollection", features: [] } as const;

function areaData(overlay: TripOverlay | null) {
  if (!overlay) return EMPTY;
  const features: object[] = overlay.anchors.flatMap((a) =>
    a.geometry
      ? [{ type: "Feature", properties: { idx: a.index }, geometry: a.geometry }]
      : [],
  );
  if (overlay.combined) {
    features.push({
      type: "Feature",
      properties: { idx: OVERLAP_IDX },
      geometry: overlay.combined as Geometry,
    });
  }
  return { type: "FeatureCollection", features };
}

const only = (idx: number) => ["==", ["get", "idx"], idx] as never;

function addLayers(map: MaplibreMap, theme: ResolvedTheme) {
  const style = TRI_STYLE[theme];
  const anchor = overlayAnchorId(map.getStyle().layers, theme);
  map.addSource(SOURCE, { type: "geojson", data: EMPTY as never });

  // The faint per-place fills sit under the labels; the outlines and the overlap go on
  // top of everything, as the single-place reach outline does, because the score cells
  // are added later and would otherwise cover them.
  style.anchors.slice(0, MAX_ANCHORS).forEach((a, i) => {
    map.addLayer(
      {
        id: anchorLayer(i, "fill"),
        type: "fill",
        source: SOURCE,
        filter: only(i),
        paint: { "fill-color": a.line, "fill-opacity": 0.06 },
      },
      anchor,
    );
  });
  map.addLayer({
    id: OVERLAP_FILL,
    type: "fill",
    source: SOURCE,
    filter: only(OVERLAP_IDX),
    paint: { "fill-color": style.overlap.fill, "fill-opacity": style.overlap.fillOpacity },
  });
  style.anchors.slice(0, MAX_ANCHORS).forEach((a, i) => {
    map.addLayer({
      id: anchorLayer(i, "casing"),
      type: "line",
      source: SOURCE,
      filter: only(i),
      layout: { "line-join": "round" },
      paint: { "line-color": style.casing, "line-width": 6, "line-opacity": 0.9 },
    });
    map.addLayer({
      id: anchorLayer(i, "line"),
      type: "line",
      source: SOURCE,
      filter: only(i),
      layout: { "line-join": "round" },
      paint: {
        "line-color": a.line,
        "line-width": 3,
        ...(a.dash ? { "line-dasharray": [...a.dash] } : {}),
      },
    });
  });
  map.addLayer({
    id: OVERLAP_CASING,
    type: "line",
    source: SOURCE,
    filter: only(OVERLAP_IDX),
    layout: { "line-join": "round", "line-cap": "round" },
    paint: { "line-color": style.overlap.casing, "line-width": 8, "line-opacity": 0.95 },
  });
  map.addLayer({
    id: OVERLAP_LINE,
    type: "line",
    source: SOURCE,
    filter: only(OVERLAP_IDX),
    layout: { "line-join": "round", "line-cap": "round" },
    paint: { "line-color": style.overlap.line, "line-width": 4.5 },
  });
}

function removeLayers(map: MaplibreMap) {
  for (const id of ALL_LAYERS) {
    if (map.getLayer(id)) map.removeLayer(id);
  }
  if (map.getSource(SOURCE)) map.removeSource(SOURCE);
}

function pinElement(
  pin: TripOverlay["pins"][number],
  theme: ResolvedTheme,
): HTMLElement {
  const style = TRI_STYLE[theme];
  const color = style.anchors[Math.min(pin.index, MAX_ANCHORS - 1)].line;
  const element = document.createElement("div");
  element.dataset.triPin = String(pin.index);
  element.setAttribute("role", "img");
  element.setAttribute("aria-label", pin.index === 0 ? "Your place" : `Point ${pin.index}`);
  element.textContent = PIN_LABELS[pin.index] ?? "";
  Object.assign(element.style, {
    width: "26px",
    height: "26px",
    borderRadius: "50%",
    display: "grid",
    placeItems: "center",
    background: color,
    color: theme === "dark" ? "#111827" : "#ffffff",
    border: `2px solid ${style.casing}`,
    boxShadow: "0 1px 4px rgba(0,0,0,0.45)",
    font: "700 12px/1 system-ui, sans-serif",
    pointerEvents: "none",
  });
  return element;
}

interface Options {
  mapRef: RefObject<MaplibreMap | null>;
  ready: boolean;
  theme: ResolvedTheme;
  /** What the planner draws; `null` (or no anchors) draws nothing. */
  overlay: TripOverlay | null;
}

/**
 * Draws the triangulation: one outlined area per place (a distinct dash pattern each,
 * so colour is not the only cue), the white-filled overlap with a heavy outline, and
 * a numbered pin per place. Rebuilt whenever the style reloads (theme change) and
 * removed on cleanup.
 */
export function useTriangulationLayers({ mapRef, ready, theme, overlay }: Options) {
  const latest = useLatest(overlay);
  const active = overlay !== null && overlay.anchors.length > 0;

  // Layers: (re)built with the style.
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !active) return;
    let cancelled = false;

    const build = () => {
      if (cancelled || map.getSource(SOURCE)) return;
      addLayers(map, theme);
      (map.getSource(SOURCE) as GeoJSONSource | undefined)?.setData(
        areaData(latest.current) as never,
      );
    };
    // isStyleLoaded() can stay false while basemap tiles load; retry when idle.
    const tryBuild = () => {
      if (cancelled) return;
      try {
        build();
      } catch {
        map.once("idle", tryBuild);
      }
    };
    tryBuild();
    map.on("style.load", build);

    return () => {
      cancelled = true;
      try {
        map.off("idle", tryBuild);
        map.off("style.load", build);
        removeLayers(map);
      } catch {
        // The map is already gone.
      }
    };
  }, [mapRef, ready, active, theme, latest]);

  // New shapes for the existing layers.
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !active) return;
    try {
      (map.getSource(SOURCE) as GeoJSONSource | undefined)?.setData(areaData(overlay) as never);
    } catch {
      // Not loaded yet: `build` applies the latest data.
    }
  }, [mapRef, ready, active, overlay]);

  // Pins.
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !overlay) return;
    const markers = overlay.pins.map((pin) =>
      new Marker({ element: pinElement(pin, theme) })
        .setLngLat([pin.lon, pin.lat])
        .addTo(map),
    );
    return () => {
      for (const marker of markers) {
        try {
          marker.remove();
        } catch {
          // The map is already gone.
        }
      }
    };
  }, [mapRef, ready, theme, overlay]);
}
