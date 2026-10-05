import {
  FACTOR_KEY_LIST,
  type FactorKey,
  type PriorityQuery,
  type Similar,
  type SimilarArea,
  type SimilarDifference,
  type SubScores,
} from "@/lib/api/types";
import { DEFAULT_FACTOR_WEIGHTS, NULL_SCORE } from "@/lib/scores/matrix";
import { haversineM } from "@/lib/scores/topk";
import { formatDistance } from "@/lib/units";

import {
  NO_METRO,
  areaName,
  areaSubScores,
  findAreaIndex,
  type AreaScores,
} from "./areaScores";

/**
 * GET /v1/similar computed in the browser from the area-score file. Mirrors
 * api/similar.py: candidates are the other areas of the source's metro, every
 * factor is z-scored against that metro (population mean and std over the
 * non-null scores; a missing score or a zero-variance factor counts as the
 * average), the nearest `OVERFETCH` by full-profile L2 distance are re-ranked
 * on the selected factors when the caller chose any (weights scaled to sum to
 * 13), and the result is spread out so none is within `minSeparationMi` of the
 * point or of another result. The candidates are areas, where the API's are
 * grid cells, so ranks can differ slightly; the shape is identical.
 */

/** L2 distance (13 z-score dimensions) at which similarity reaches 0. */
export const SIMILARITY_MAX_DIST = 6;
const DIFF_MIN_POINTS = 6;
const MAX_DIFFS = 3;
const OVERFETCH_FACTOR = 20;
const OVERFETCH_MAX = 200;
const SIMILARITY_DIM = 13;

const SHORT_LABELS: Record<FactorKey, string> = {
  grocery: "grocery",
  gym: "gyms",
  cafe: "cafes",
  restaurant: "restaurants",
  bar: "bars",
  shopping: "shopping",
  gasConvenience: "gas and convenience",
  transit: "transit",
  school: "schools",
  traffic: "traffic",
  emergencyCorridor: "noise",
  airport: "airport access",
  recreation: "parks and trails",
};

const COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"] as const;

export function compass(fromLat: number, fromLon: number, toLat: number, toLon: number): string {
  const rad = Math.PI / 180;
  const y = Math.sin((toLon - fromLon) * rad) * Math.cos(toLat * rad);
  const x =
    Math.cos(fromLat * rad) * Math.sin(toLat * rad) -
    Math.sin(fromLat * rad) * Math.cos(toLat * rad) * Math.cos((toLon - fromLon) * rad);
  const bearing = (((Math.atan2(y, x) / rad) % 360) + 360) % 360;
  return COMPASS[Math.floor((bearing + 22.5) / 45) % 8];
}

export function similarityOf(dist: number): number {
  return Math.floor(100 * Math.max(0, 1 - dist / SIMILARITY_MAX_DIST) + 0.5);
}

function roundSigned(value: number): number {
  return Math.sign(value) * Math.floor(Math.abs(value) + 0.5);
}

function summary(diffs: readonly SimilarDifference[]): string {
  if (diffs.length === 0) return "Very similar across all factors.";
  const text = diffs
    .map((d) => {
      const n = Math.abs(d.delta);
      return `${n} ${n === 1 ? "point" : "points"} ${d.delta > 0 ? "better" : "weaker"} for ${d.label}`;
    })
    .join(", ");
  return `${text[0].toUpperCase()}${text.slice(1)}.`;
}

function differences(
  target: SubScores,
  row: SubScores,
  order: readonly FactorKey[],
  selected: ReadonlySet<FactorKey>,
): SimilarDifference[] {
  const found: { size: number; factor: FactorKey; delta: number }[] = [];
  for (const factor of order) {
    if (!selected.has(factor)) continue;
    const a = target[factor];
    const b = row[factor];
    if (a === null || a === undefined || b === null || b === undefined) continue;
    const delta = b - a;
    if (Math.abs(delta) >= DIFF_MIN_POINTS) found.push({ size: Math.abs(delta), factor, delta });
  }
  found.sort((p, q) => q.size - p.size); // stable, so ties keep factor order
  return found.slice(0, MAX_DIFFS).map(({ factor, delta }) => ({
    factor,
    label: SHORT_LABELS[factor],
    delta: roundSigned(delta),
  }));
}

export interface LocalSimilarQuery extends PriorityQuery {
  lat: number;
  lon: number;
  /** The place's own sub-scores (what the API compares against). */
  source: SubScores;
  /** The place's area id, when known; otherwise the nearest area centre is used. */
  areaId?: number | null;
  k?: number;
  minSeparationMi?: number;
}

function nearestArea(areas: AreaScores, lat: number, lon: number): number {
  const cos = Math.cos((lat * Math.PI) / 180);
  let best = -1;
  let bestD = Infinity;
  for (let i = 0; i < areas.count; i++) {
    const dy = areas.lat[i] - lat;
    const dx = (areas.lon[i] - lon) * cos;
    const d = dx * dx + dy * dy;
    if (d < bestD) {
      bestD = d;
      best = i;
    }
  }
  return best;
}

/** The areas most like the source, or `null` when the file cannot answer. */
export function localSimilar(areas: AreaScores, query: LocalSimilarQuery): Similar | null {
  const { lat, lon, source } = query;
  const k = query.k ?? 5;
  const minSeparationMi = query.minSeparationMi ?? 1;
  const width = areas.factors.length;

  let sourceIndex = query.areaId != null ? findAreaIndex(areas, query.areaId) : -1;
  if (sourceIndex === -1) sourceIndex = nearestArea(areas, lat, lon);
  if (sourceIndex === -1) return null;
  const metro = areas.metroIndex[sourceIndex];
  if (metro === NO_METRO) return null;

  const members: number[] = [];
  for (let i = 0; i < areas.count; i++) if (areas.metroIndex[i] === metro) members.push(i);

  // Per-metro population mean and std over the non-null scores.
  const mean = new Float64Array(width);
  const std = new Float64Array(width);
  for (let f = 0; f < width; f++) {
    let sum = 0;
    let n = 0;
    for (const i of members) {
      const v = areas.scores[i * width + f];
      if (v !== NULL_SCORE) {
        sum += v;
        n += 1;
      }
    }
    if (n === 0) continue;
    mean[f] = sum / n;
    let sq = 0;
    for (const i of members) {
      const v = areas.scores[i * width + f];
      if (v !== NULL_SCORE) sq += (v - mean[f]) ** 2;
    }
    std[f] = Math.sqrt(sq / n);
  }
  const z = (value: number | null | undefined, f: number) =>
    value === null || value === undefined || value === NULL_SCORE || !(std[f] > 0)
      ? 0
      : (value - mean[f]) / std[f];

  const target = new Float64Array(width);
  areas.factors.forEach((key, f) => {
    target[f] = z(source[key], f);
  });

  const explicit =
    query.factors !== undefined || Object.keys(query.weights ?? {}).length > 0;
  const selectedKeys: readonly FactorKey[] =
    query.factors && query.factors.length > 0 ? query.factors : FACTOR_KEY_LIST;
  const selected = new Set<FactorKey>(selectedKeys);

  // Full-profile distance, nearest first (ties by area order, like a stable sort).
  const pool = members
    .filter((i) => i !== sourceIndex)
    .map((i) => {
      let total = 0;
      for (let f = 0; f < width; f++) {
        total += (z(areas.scores[i * width + f], f) - target[f]) ** 2;
      }
      return { index: i, dist: Math.sqrt(total) };
    })
    .sort((a, b) => a.dist - b.dist);
  let candidates = pool.slice(
    0,
    explicit ? OVERFETCH_MAX : Math.min(k * OVERFETCH_FACTOR, OVERFETCH_MAX),
  );

  if (explicit) {
    const dims: { f: number; weight: number }[] = [];
    for (const key of selectedKeys) {
      const f = areas.factors.indexOf(key);
      const weight = query.weights?.[key] ?? DEFAULT_FACTOR_WEIGHTS[key];
      if (f !== -1 && weight > 0) dims.push({ f, weight });
    }
    const total = dims.reduce((sum, d) => sum + d.weight, 0);
    if (total > 0) {
      const scale = SIMILARITY_DIM / total;
      candidates = candidates
        .map(({ index }) => {
          let sum = 0;
          for (const { f, weight } of dims) {
            sum += weight * scale * (z(areas.scores[index * width + f], f) - target[f]) ** 2;
          }
          return { index, dist: Math.sqrt(sum) };
        })
        .sort((a, b) => a.dist - b.dist);
    }
  }

  const minM = minSeparationMi * 1609.344;
  const chosen: { index: number; dist: number }[] = [];
  for (const c of candidates) {
    const cLat = areas.lat[c.index];
    const cLon = areas.lon[c.index];
    if (haversineM(lat, lon, cLat, cLon) < minM) continue;
    if (chosen.some((p) => haversineM(areas.lat[p.index], areas.lon[p.index], cLat, cLon) < minM)) {
      continue;
    }
    chosen.push(c);
    if (chosen.length === k) break;
  }

  const results = chosen.map(({ index, dist }): SimilarArea => {
    const subScores = areaSubScores(areas, index);
    const diffs = differences(source, subScores, areas.factors, selected);
    const cLat = areas.lat[index];
    const cLon = areas.lon[index];
    return {
      neighborhood: areaName(areas, index),
      latitude: cLat,
      longitude: cLon,
      direction: compass(lat, lon, cLat, cLon),
      distanceLabel: formatDistance(haversineM(lat, lon, cLat, cLon)),
      similarity: similarityOf(dist),
      compositeScore: defaultComposite(areas, index),
      areaLabel: null,
      differences: diffs,
      summary: summary(diffs),
    };
  });
  return { minSeparationMi, results, priorities: [...selectedKeys] };
}

/** The stored (default-weight) composite, rounded half up like the API's. */
function defaultComposite(areas: AreaScores, index: number): number {
  const width = areas.factors.length;
  let weighted = 0;
  let total = 0;
  areas.factors.forEach((key, f) => {
    const v = areas.scores[index * width + f];
    if (v === NULL_SCORE) return;
    weighted += DEFAULT_FACTOR_WEIGHTS[key] * v;
    total += DEFAULT_FACTOR_WEIGHTS[key];
  });
  return total > 0 ? Math.floor(weighted / total + 0.5) : 0;
}
