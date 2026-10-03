import type { Bbox } from "@/lib/api/types";

/** The covered metro, west/south/east/north. */
export const METRO_BBOX: Bbox = [-75.2, 39.85, -71.85, 42.0];

/** Where the map opens when nothing in the URL says otherwise: New York City. */
export const INITIAL_CENTER = { lat: 40.73, lon: -73.99 } as const;

/** Zoom levels closer than the whole-metro fit; the same as clicking + four times. */
export const INITIAL_ZOOM_IN_LEVELS = 4;

/** The default camera, given the zoom at which the metro box fits the viewport. */
export function initialMetroView(fittedZoom: number): MapView {
  return { ...INITIAL_CENTER, zoom: fittedZoom + INITIAL_ZOOM_IN_LEVELS };
}

/** Below this zoom ~1 km cells are too small to see and too many to fetch. */
export const FINE_CELL_MIN_ZOOM = 10;

/** Enough for a full desktop viewport at the finest zoom without truncating. */
export const CELL_LIMIT = 12_000;

export interface MapView {
  lat: number;
  lon: number;
  zoom: number;
}

export function precisionForZoom(zoom: number): 5 | 6 {
  return zoom < FINE_CELL_MIN_ZOOM ? 5 : 6;
}

const clamp = (value: number, min: number, max: number) =>
  Math.min(max, Math.max(min, value));

/**
 * Grows the box by `ratio` of its size on each side, so a small pan reveals
 * cells that are already loaded instead of an empty edge.
 */
export function padBbox([west, south, east, north]: Bbox, ratio = 0.15): Bbox {
  const dx = (east - west) * ratio;
  const dy = (north - south) * ratio;
  return [
    clamp(west - dx, -180, 180),
    clamp(south - dy, -90, 90),
    clamp(east + dx, -180, 180),
    clamp(north + dy, -90, 90),
  ];
}

/** Rounds so tiny pans do not produce a new request key. */
export function roundBbox(bbox: Bbox, decimals = 3): Bbox {
  const f = 10 ** decimals;
  return bbox.map((v) => Math.round(v * f) / f) as unknown as Bbox;
}

export function bboxKey(bbox: Bbox): string {
  return bbox.join(",");
}
