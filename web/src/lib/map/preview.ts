import type { AreaGeometry, Bbox } from "@/lib/api/types";

export type PreviewKind = "similar" | "improve" | "best-move";

export interface PreviewSummary {
  compositeScore?: number;
  differences?: { label: string; delta: number }[];
  distanceLabel?: string;
  direction?: string;
}

/** A candidate place shown on the map without becoming the selected location. */
export interface Preview {
  lat: number;
  lon: number;
  label: string;
  /** Small muted line under the title, e.g. the street boundary or what it improves. */
  subtitle?: string;
  kind: PreviewKind;
  summary?: PreviewSummary;
}

/** Roughly a neighbourhood: keeps a ~1.5 sq mi polygon inside a fitted point. */
const POINT_PADDING_DEG = 0.012;
/** Beyond this span (about 7 mi) fitting both places would zoom out too far. */
const MAX_BOTH_SPAN_DEG = 0.1;

function around(lat: number, lon: number): Bbox {
  return [
    lon - POINT_PADDING_DEG,
    lat - POINT_PADDING_DEG,
    lon + POINT_PADDING_DEG,
    lat + POINT_PADDING_DEG,
  ];
}

function union(a: Bbox, b: Bbox): Bbox {
  return [
    Math.min(a[0], b[0]),
    Math.min(a[1], b[1]),
    Math.max(a[2], b[2]),
    Math.max(a[3], b[3]),
  ];
}

/** The camera for a preview: both places when they sit close, else the preview alone. */
export function previewBounds(
  preview: { lat: number; lon: number },
  origin: { lat: number; lon: number } | null,
): Bbox {
  const own = around(preview.lat, preview.lon);
  if (!origin) return own;
  const both = union(own, around(origin.lat, origin.lon));
  const span = Math.max(both[2] - both[0], both[3] - both[1]);
  return span <= MAX_BOTH_SPAN_DEG ? both : own;
}

function visit(coordinates: unknown, each: (lon: number, lat: number) => void) {
  if (!Array.isArray(coordinates)) return;
  if (typeof coordinates[0] === "number") {
    each(coordinates[0], coordinates[1] as number);
    return;
  }
  coordinates.forEach((child) => visit(child, each));
}

/** The box around an area polygon, or around the point when there is none. */
export function originBounds(
  origin: { lat: number; lon: number },
  geometry: AreaGeometry | null,
): Bbox {
  const pad = around(origin.lat, origin.lon);
  if (!geometry) return pad;
  let box: Bbox | null = null;
  visit(geometry.coordinates, (lon, lat) => {
    box = box ? union(box, [lon, lat, lon, lat]) : [lon, lat, lon, lat];
  });
  return box ? union(box, [origin.lon, origin.lat, origin.lon, origin.lat]) : pad;
}
