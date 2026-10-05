import type { AreaGeometry, FactorKey, PlacePin } from "@/lib/api/types";

/** The factors backed by named places (what `/places/around` serves). */
export const PIN_FACTORS: readonly FactorKey[] = [
  "grocery",
  "gym",
  "cafe",
  "restaurant",
  "bar",
  "shopping",
  "recreation",
  "gasConvenience",
  "transit",
  "school",
];

export const MAX_PINS = 150;
export const PER_FACTOR = 15;
export const CLUSTER_RADIUS_PX = 40;

const DEFAULT_RADIUS_MI = 0.5;
const MIN_RADIUS_MI = 0.25;
const MAX_RADIUS_MI = 1.5;
const RADIUS_MARGIN_MI = 0.15;
const MI_PER_DEG_LAT = 69.0;

/** What one place of a factor is called ("Restaurant"). */
export const PIN_KIND: Partial<Record<FactorKey, string>> = {
  grocery: "Grocery",
  gym: "Gym",
  cafe: "Cafe",
  restaurant: "Restaurant",
  bar: "Bar",
  shopping: "Shopping",
  recreation: "Park",
  gasConvenience: "Gas & convenience",
  transit: "Transit stop",
  school: "School",
};

/** Plural, lower case, for a cluster summary ("8 restaurants"). */
export const PIN_KIND_PLURAL: Partial<Record<FactorKey, string>> = {
  grocery: "grocery stores",
  gym: "gyms",
  cafe: "cafes",
  restaurant: "restaurants",
  bar: "bars",
  shopping: "shops",
  recreation: "parks",
  gasConvenience: "gas & convenience stops",
  transit: "transit stops",
  school: "schools",
};

/** The selected factors that have named places, in a stable order. */
export function pinFactors(selected: readonly FactorKey[]): FactorKey[] {
  return PIN_FACTORS.filter((factor) => selected.includes(factor));
}

export interface PlaceSearch {
  lat: number;
  lon: number;
  radiusMi: number;
}

function* positions(geometry: AreaGeometry): Generator<readonly number[]> {
  const polygons =
    geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
  for (const polygon of polygons) {
    for (const ring of polygon) yield* ring;
  }
}

/**
 * Where and how far to look for pins. With an area polygon: its bbox centre
 * and half-diagonal plus a margin, clamped to 0.25-1.5 mi; without: the point
 * and 0.5 mi.
 */
export function placeSearch(
  point: { lat: number; lon: number },
  geometry: AreaGeometry | null | undefined,
): PlaceSearch {
  if (!geometry) return { ...point, radiusMi: DEFAULT_RADIUS_MI };
  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;
  for (const [lon, lat] of positions(geometry)) {
    west = Math.min(west, lon);
    east = Math.max(east, lon);
    south = Math.min(south, lat);
    north = Math.max(north, lat);
  }
  if (![west, south, east, north].every(Number.isFinite)) {
    return { ...point, radiusMi: DEFAULT_RADIUS_MI };
  }
  const lat = (south + north) / 2;
  const heightMi = (north - south) * MI_PER_DEG_LAT;
  const widthMi = (east - west) * MI_PER_DEG_LAT * Math.cos((lat * Math.PI) / 180);
  const half = Math.hypot(heightMi, widthMi) / 2 + RADIUS_MARGIN_MI;
  const radiusMi = Math.min(MAX_RADIUS_MI, Math.max(MIN_RADIUS_MI, half));
  return {
    lat: Math.round(lat * 1e5) / 1e5,
    lon: Math.round(((west + east) / 2) * 1e5) / 1e5,
    radiusMi: Math.round(radiusMi * 100) / 100,
  };
}

/** A pin with its stable identity (the same place keeps the same key). */
export interface KeyedPin extends PlacePin {
  key: string;
}

/** Keys the places, drops duplicates and caps the total. */
export function keyPins(places: readonly PlacePin[], max = MAX_PINS): KeyedPin[] {
  const seen = new Set<string>();
  const out: KeyedPin[] = [];
  for (const place of places) {
    const key = `${place.factor}|${place.name}|${place.latitude.toFixed(5)}|${place.longitude.toFixed(5)}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ ...place, key });
    if (out.length >= max) break;
  }
  return out;
}

export interface ScreenPoint {
  x: number;
  y: number;
}

export interface Cluster<T extends ScreenPoint> {
  members: T[];
  /** Centroid of the members on screen. */
  x: number;
  y: number;
}

/**
 * Greedy screen-space clustering: each point joins the nearest existing
 * cluster whose centroid is within `radiusPx`, otherwise it starts one. Input
 * order decides ties, so equal input gives equal clusters.
 */
export function clusterScreenPoints<T extends ScreenPoint>(
  points: readonly T[],
  radiusPx: number = CLUSTER_RADIUS_PX,
): Cluster<T>[] {
  const clusters: Cluster<T>[] = [];
  for (const point of points) {
    let best: Cluster<T> | null = null;
    let bestDistance = Infinity;
    for (const cluster of clusters) {
      const distance = Math.hypot(cluster.x - point.x, cluster.y - point.y);
      if (distance <= radiusPx && distance < bestDistance) {
        best = cluster;
        bestDistance = distance;
      }
    }
    if (best) {
      const n = best.members.length;
      best.x = (best.x * n + point.x) / (n + 1);
      best.y = (best.y * n + point.y) / (n + 1);
      best.members.push(point);
    } else {
      clusters.push({ members: [point], x: point.x, y: point.y });
    }
  }
  return clusters;
}

/** Factor counts of a cluster, most common first (ties in factor order). */
export function factorCounts(
  members: readonly { factor: FactorKey }[],
): { factor: FactorKey; count: number }[] {
  const counts = new Map<FactorKey, number>();
  for (const { factor } of members) counts.set(factor, (counts.get(factor) ?? 0) + 1);
  return [...counts]
    .map(([factor, count]) => ({ factor, count }))
    .sort((a, b) => b.count - a.count);
}

/** "12 places: 8 restaurants, 4 bars". */
export function clusterLabel(members: readonly { factor: FactorKey }[]): string {
  const parts = factorCounts(members).map(
    ({ factor, count }) =>
      `${count} ${count === 1 ? (PIN_KIND[factor] ?? factor).toLowerCase() : (PIN_KIND_PLURAL[factor] ?? factor)}`,
  );
  return `${members.length} places: ${parts.join(", ")}`;
}

/** "Name · Restaurant · 0.2 mi". */
export function pinLabel(pin: PlacePin): string {
  const kind = PIN_KIND[pin.factor] ?? pin.factor;
  return `${pin.name} · ${kind} · ${pin.distanceMi.toFixed(1)} mi`;
}
