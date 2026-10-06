"use client";

import { addProtocol, type Map as MaplibreMap } from "maplibre-gl";
import { useEffect, useRef, type RefObject } from "react";

import { useLatest } from "@/hooks/useLatest";
import { useTilesUrl } from "@/hooks/useStaticData";
import { CELL_OPACITY, RAMP_STOPS } from "@/lib/map/colors";
import { overlayAnchorId } from "@/lib/map/overlayAnchor";
import {
  TILE_LAYER_FOR_PRECISION,
  diffTileScores,
  tileScoresOf,
  type TileCells,
  type TileScores,
} from "@/lib/map/tileScores";
import { firstWaterMaskId, isOverWater } from "@/lib/map/waterMask";
import type { ResolvedTheme } from "@/lib/theme";

import type { CellClick } from "./MapCanvas";

const SOURCE = "tiles";
const FILL = { cells: "tiles-cells-fill", parents: "tiles-parents-fill" } as const;
const OUTLINE = "tiles-cells-outline";
const HIGHLIGHT_CASING = "tiles-highlight-casing";
const HIGHLIGHT = "tiles-highlight";
const AREAS_LINE = "tiles-areas-line";
// Invisible: only there so a click can ask which area it landed in.
const AREAS_HIT = "tiles-areas-hit";

type TileLayerName = keyof typeof FILL;

let protocolReady: Promise<void> | null = null;

/** Registers `pmtiles://` once; the library is fetched only when tiles are on. */
function ensureProtocol(): Promise<void> {
  protocolReady ??= import("pmtiles").then(({ Protocol }) => {
    const protocol = new Protocol();
    addProtocol("pmtiles", protocol.tile);
  });
  return protocolReady;
}

const scoreState = ["coalesce", ["feature-state", "score"], 0];
const FILL_COLOR = [
  "interpolate",
  ["linear"],
  scoreState,
  ...RAMP_STOPS.flat(),
] as never;

function addTileLayers(map: MaplibreMap, theme: ResolvedTheme, url: string) {
  // Under the water mask when there is one (cells < water < overlays); the mask
  // is already above these layers, so nothing needs moving afterwards.
  const anchor = firstWaterMaskId(map) ?? overlayAnchorId(map.getStyle().layers, theme);
  // A cell has no colour until the score file has given it a state.
  const opacity = [
    "case",
    ["==", ["feature-state", "score"], null],
    0,
    CELL_OPACITY[theme],
  ] as never;
  map.addSource(SOURCE, {
    type: "vector",
    url: `pmtiles://${url}`,
    promoteId: { cells: "g", parents: "g", areas: "id" },
  });
  for (const name of ["parents", "cells"] as const) {
    map.addLayer(
      {
        id: FILL[name],
        type: "fill",
        source: SOURCE,
        "source-layer": name,
        paint: {
          "fill-color": FILL_COLOR,
          "fill-opacity": opacity,
          "fill-antialias": false,
        },
      },
      anchor,
    );
  }
  map.addLayer(
    {
      id: OUTLINE,
      type: "line",
      source: SOURCE,
      "source-layer": "cells",
      minzoom: 11,
      paint: { "line-color": "#ffffff", "line-opacity": 0.35, "line-width": 0.5 },
    },
    anchor,
  );
  map.addLayer(
    {
      id: AREAS_LINE,
      type: "line",
      source: SOURCE,
      "source-layer": "areas",
      minzoom: 11,
      paint: {
        "line-color": theme === "dark" ? "#93c5fd" : "#1d4ed8",
        "line-opacity": 0.35,
        "line-width": 1,
      },
    },
    anchor,
  );
  map.addLayer(
    {
      id: AREAS_HIT,
      type: "fill",
      source: SOURCE,
      "source-layer": "areas",
      minzoom: 11,
      paint: { "fill-color": "#000000", "fill-opacity": 0 },
    },
    anchor,
  );
  const none = ["==", ["get", "g"], ""] as never;
  map.addLayer({
    id: HIGHLIGHT_CASING,
    type: "line",
    source: SOURCE,
    "source-layer": "cells",
    filter: none,
    paint: { "line-color": "#111111", "line-width": 5 },
  });
  map.addLayer({
    id: HIGHLIGHT,
    type: "line",
    source: SOURCE,
    "source-layer": "cells",
    filter: none,
    paint: { "line-color": "#ffffff", "line-width": 2.5 },
  });
}

/** The one area under a screen point, or `undefined` when there is none or it is ambiguous. */
function areaIdAt(map: MaplibreMap, point: { x: number; y: number }): number | undefined {
  try {
    if (!map.getLayer(AREAS_HIT)) return undefined;
    const ids = new Set(
      map
        .queryRenderedFeatures(point as never, { layers: [AREAS_HIT] })
        .map((feature) => Number(feature.properties?.id ?? feature.id)),
    );
    if (ids.size !== 1) return undefined;
    const [id] = ids;
    return Number.isInteger(id) ? id : undefined;
  } catch {
    return undefined;
  }
}

interface Applied {
  layer: TileLayerName;
  scores: TileScores;
}

/** Brings the tiles' feature-states in line with `cells`; returns what is now set. */
function applyScores(map: MaplibreMap, cells: TileCells, applied: Applied): Applied {
  const layer: TileLayerName = TILE_LAYER_FOR_PRECISION[cells.precision];
  const next = tileScoresOf(cells);
  const sameLayer = applied.layer === layer;
  if (!sameLayer) {
    // A precision switch changes the source layer: clear the old one.
    for (const id of applied.scores.keys()) {
      map.removeFeatureState({ source: SOURCE, sourceLayer: applied.layer, id });
    }
  }
  const { set, remove } = diffTileScores(sameLayer ? applied.scores : new Map(), next);
  for (const [id, score] of set) {
    map.setFeatureState({ source: SOURCE, sourceLayer: layer, id }, { score });
  }
  for (const id of remove) {
    map.removeFeatureState({ source: SOURCE, sourceLayer: layer, id });
  }
  map.setLayoutProperty(FILL.cells, "visibility", layer === "cells" ? "visible" : "none");
  map.setLayoutProperty(FILL.parents, "visibility", layer === "parents" ? "visible" : "none");
  return { layer, scores: next };
}

interface Options {
  mapRef: RefObject<MaplibreMap | null>;
  ready: boolean;
  theme: ResolvedTheme;
  /** Local scores for the view; `null` leaves the GeoJSON layers in charge. */
  tileCells: TileCells | null;
  highlightGeohash: string | null;
  onCellClick: (cell: CellClick) => void;
  onFailed: () => void;
}

/**
 * Draws the cell grid from a PMTiles archive (`NEXT_PUBLIC_PMTILES_URL`, or
 * the static manifest's `tiles`) and
 * colours it by feature-state from scores computed in the browser. Does
 * nothing unless the flag is set and the tiles' scores are known; on a tile
 * error it calls `onFailed` so the GeoJSON layers take over again.
 */
export function usePmtilesCells({
  mapRef,
  ready,
  theme,
  tileCells,
  highlightGeohash,
  onCellClick,
  onFailed,
}: Options) {
  const tilesUrl = useTilesUrl();
  const active = Boolean(tilesUrl) && tileCells !== null;
  const latest = useLatest({ tileCells, highlightGeohash, onCellClick, onFailed });
  const applied = useRef<Applied>({
    layer: "cells",
    scores: new Map(),
  });

  // Layers, the click handler and failure handling: (re)built with the style.
  useEffect(() => {
    const map = mapRef.current;
    const url = tilesUrl;
    if (!ready || !map || !url || !active) return;
    let cancelled = false;

    const apply = () => {
      const cells = latest.current.tileCells;
      if (!cells || !map.getSource(SOURCE)) return;
      applied.current = applyScores(map, cells, applied.current);
    };

    const build = () => {
      if (cancelled || map.getSource(SOURCE)) return;
      addTileLayers(map, theme, url);
      applied.current = { layer: "cells", scores: new Map() };
      const filter = ["==", ["get", "g"], latest.current.highlightGeohash ?? ""] as never;
      map.setFilter(HIGHLIGHT_CASING, filter);
      map.setFilter(HIGHLIGHT, filter);
      apply();
    };
    const onError = (event: unknown) => {
      if ((event as { sourceId?: string }).sourceId === SOURCE) latest.current.onFailed();
    };
    const onClick = (event: {
      features?: { properties?: Record<string, unknown>; state?: Record<string, unknown> }[];
      lngLat: { lat: number; lng: number };
      point: { x: number; y: number };
    }) => {
      if (isOverWater(map, event.point)) return;
      const feature = event.features?.[0];
      const geohash = feature?.properties?.g;
      const score = Number(feature?.state?.score);
      if (typeof geohash !== "string" || !Number.isFinite(score)) return;
      latest.current.onCellClick({
        geohash,
        areaId: areaIdAt(map, event.point),
        score,
        lat: event.lngLat.lat,
        lon: event.lngLat.lng,
      });
    };
    const setPointer = (value: string) => () => {
      map.getCanvas().style.cursor = value;
    };
    const enter = setPointer("pointer");
    const leave = setPointer("");

    // isStyleLoaded() stays false while basemap tiles are still loading, long after
    // style.load has fired, so try now and retry when the map next goes idle.
    const tryBuild = () => {
      if (cancelled) return;
      try {
        build();
      } catch {
        map.once("idle", tryBuild);
      }
    };

    void ensureProtocol().then(() => {
      if (cancelled) return;
      tryBuild();
      map.on("style.load", build);
      map.on("error", onError);
      map.on("click", FILL.cells, onClick);
      map.on("mouseenter", FILL.cells, enter);
      map.on("mouseleave", FILL.cells, leave);
    });

    return () => {
      cancelled = true;
      try {
        map.off("idle", tryBuild);
        map.off("style.load", build);
        map.off("error", onError);
        map.off("click", FILL.cells, onClick);
        map.off("mouseenter", FILL.cells, enter);
        map.off("mouseleave", FILL.cells, leave);
        for (const id of [HIGHLIGHT, HIGHLIGHT_CASING, AREAS_HIT, AREAS_LINE, OUTLINE, FILL.cells, FILL.parents]) {
          if (map.getLayer(id)) map.removeLayer(id);
        }
        if (map.getSource(SOURCE)) map.removeSource(SOURCE);
      } catch {
        // The map is already gone.
      }
    };
  }, [mapRef, ready, active, theme, latest, tilesUrl]);

  // New scores for the view.
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !active || !map.getSource(SOURCE)) return;
    if (!tileCells) return;
    applied.current = applyScores(map, tileCells, applied.current);
  }, [mapRef, ready, active, tileCells]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !active || !map.getLayer(HIGHLIGHT)) return;
    const filter = ["==", ["get", "g"], highlightGeohash ?? ""] as never;
    map.setFilter(HIGHLIGHT_CASING, filter);
    map.setFilter(HIGHLIGHT, filter);
  }, [mapRef, ready, active, highlightGeohash]);
}
