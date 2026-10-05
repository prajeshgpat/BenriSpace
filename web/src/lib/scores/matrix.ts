import { decodeBounds, type GeohashBounds } from "@/lib/map/geohash";
import { FACTOR_KEY_LIST, type FactorKey, type SubScores } from "@/lib/api/types";

/** Marks a missing sub-score in the file. */
export const NULL_SCORE = 255;

/**
 * The API's default relative weight per factor (docs/SCORING.md section 2,
 * mirrored from api/factors.py). Only the ratios matter. The server's own
 * numbers, once a response has revealed them, take precedence.
 */
export const DEFAULT_FACTOR_WEIGHTS: Readonly<Record<FactorKey, number>> = {
  grocery: 14,
  gym: 9,
  cafe: 8,
  restaurant: 10,
  bar: 5,
  shopping: 4,
  gasConvenience: 6,
  transit: 14,
  school: 10,
  traffic: 4,
  emergencyCorridor: 12,
  airport: 5,
  recreation: 5,
};

export interface ScoreMatrixHeader {
  version: string | number;
  factors: FactorKey[];
  count: number;
  generatedAt: string;
}

/**
 * Every grid cell's sub-scores, decoded from the compact file. `scores` is
 * row-major: cell `i`, factor `f` lives at `i * factors.length + f`.
 */
export interface ScoreMatrix {
  header: ScoreMatrixHeader;
  count: number;
  factors: FactorKey[];
  geohashes: string[];
  scores: Uint8Array;
  /** Cell centres, for viewport tests and spacing. */
  lat: Float64Array;
  lon: Float64Array;
  /** minLon, minLat, maxLon, maxLat per cell. */
  bounds: Float64Array;
}

const FACTOR_SET = new Set<string>(FACTOR_KEY_LIST);
const GEOHASH_LENGTH = 6;

/** Throws on anything that is not a well-formed score file. */
export function decodeScoreMatrix(buffer: ArrayBuffer): ScoreMatrix {
  if (buffer.byteLength < 4) throw new Error("score file too short");
  const view = new DataView(buffer);
  const headerLength = view.getUint32(0, true);
  if (headerLength <= 0 || 4 + headerLength > buffer.byteLength) {
    throw new Error("score file header is truncated");
  }
  const decoder = new TextDecoder();
  const header = JSON.parse(
    decoder.decode(new Uint8Array(buffer, 4, headerLength)),
  ) as Partial<ScoreMatrixHeader>;
  const factors = header.factors;
  if (
    !Array.isArray(factors) ||
    factors.length === 0 ||
    !factors.every((f) => FACTOR_SET.has(f)) ||
    typeof header.count !== "number" ||
    !Number.isInteger(header.count) ||
    header.count < 0
  ) {
    throw new Error("score file header is invalid");
  }
  const { count } = header;
  const width = factors.length;
  const hashStart = 4 + headerLength;
  const scoreStart = hashStart + count * GEOHASH_LENGTH;
  if (buffer.byteLength < scoreStart + count * width) {
    throw new Error("score file body is truncated");
  }

  const hashBytes = new Uint8Array(buffer, hashStart, count * GEOHASH_LENGTH);
  const scores = new Uint8Array(buffer, scoreStart, count * width);
  const geohashes = new Array<string>(count);
  const lat = new Float64Array(count);
  const lon = new Float64Array(count);
  const bounds = new Float64Array(count * 4);
  const empty: GeohashBounds = { minLat: 0, maxLat: 0, minLon: 0, maxLon: 0 };
  for (let i = 0; i < count; i++) {
    const hash = decoder.decode(
      hashBytes.subarray(i * GEOHASH_LENGTH, (i + 1) * GEOHASH_LENGTH),
    );
    geohashes[i] = hash;
    const b = decodeBounds(hash) ?? empty;
    lat[i] = (b.minLat + b.maxLat) / 2;
    lon[i] = (b.minLon + b.maxLon) / 2;
    bounds[i * 4] = b.minLon;
    bounds[i * 4 + 1] = b.minLat;
    bounds[i * 4 + 2] = b.maxLon;
    bounds[i * 4 + 3] = b.maxLat;
  }
  return {
    header: {
      version: header.version ?? "",
      factors: factors as FactorKey[],
      count,
      generatedAt: header.generatedAt ?? "",
    },
    count,
    factors: factors as FactorKey[],
    geohashes,
    scores,
    lat,
    lon,
    bounds,
  };
}

/** What to weigh: column indexes in the file and the weight for each. */
export interface CompositeSpec {
  columns: Int32Array;
  weights: Float64Array;
}

/**
 * Same arithmetic as api/mapdata.py `composite_from_row`: weights are the
 * default weights times importance (`overrides` are absolute weights, as sent
 * to the API), summed over the selected factors that have a score and divided
 * by the weight of those factors.
 */
export function buildCompositeSpec(
  matrix: Pick<ScoreMatrix, "factors">,
  selected: readonly FactorKey[],
  overrides: Partial<Record<FactorKey, number>> | undefined,
  defaults: Partial<Record<FactorKey, number>> = {},
): CompositeSpec {
  const columns: number[] = [];
  const weights: number[] = [];
  for (const key of selected) {
    const column = matrix.factors.indexOf(key);
    if (column === -1) continue;
    const weight =
      overrides?.[key] ?? defaults[key] ?? DEFAULT_FACTOR_WEIGHTS[key];
    if (!(weight > 0)) continue;
    columns.push(column);
    weights.push(weight);
  }
  return { columns: Int32Array.from(columns), weights: Float64Array.from(weights) };
}

/** Composite 0-100 of cell `index`, or `null` when every selected factor is missing. */
export function cellComposite(
  matrix: Pick<ScoreMatrix, "scores" | "factors">,
  index: number,
  spec: CompositeSpec,
): number | null {
  const width = matrix.factors.length;
  const base = index * width;
  let weighted = 0;
  let total = 0;
  for (let j = 0; j < spec.columns.length; j++) {
    const value = matrix.scores[base + spec.columns[j]];
    if (value === NULL_SCORE) continue;
    weighted += spec.weights[j] * value;
    total += spec.weights[j];
  }
  return total > 0 ? weighted / total : null;
}

/** One composite per cell; `NaN` where the cell has no selected score. */
export function compositeAll(matrix: ScoreMatrix, spec: CompositeSpec): Float64Array {
  const out = new Float64Array(matrix.count);
  for (let i = 0; i < matrix.count; i++) {
    out[i] = cellComposite(matrix, i, spec) ?? Number.NaN;
  }
  return out;
}

/** One decimal, like the API. */
export function round1(value: number): number {
  return Math.round(value * 10) / 10;
}

export function subScoresOf(matrix: ScoreMatrix, index: number): SubScores {
  const width = matrix.factors.length;
  return Object.fromEntries(
    FACTOR_KEY_LIST.map((key) => {
      const column = matrix.factors.indexOf(key);
      if (column === -1) return [key, null];
      const value = matrix.scores[index * width + column];
      return [key, value === NULL_SCORE ? null : value];
    }),
  ) as SubScores;
}

export type Bbox4 = readonly [number, number, number, number];

/** Indexes of the cells whose centre is inside the box (west, south, east, north). */
export function cellsInBbox(matrix: ScoreMatrix, bbox: Bbox4): number[] {
  const [west, south, east, north] = bbox;
  const out: number[] = [];
  for (let i = 0; i < matrix.count; i++) {
    const la = matrix.lat[i];
    const lo = matrix.lon[i];
    if (lo >= west && lo <= east && la >= south && la <= north) out.push(i);
  }
  return out;
}

export interface LocalCells {
  geohashes: string[];
  scores: number[];
  bounds: number[][];
}

/**
 * The viewport's coloured cells, as `/map/cells` returns them: precision 6 is
 * one cell per row, precision 5 averages the composites of the finer cells
 * inside each parent (the SQL's `avg(score)`). Cells with no score are left out.
 */
export function localCells(
  matrix: ScoreMatrix,
  bbox: Bbox4,
  precision: 5 | 6,
  composites: Float64Array,
): LocalCells {
  const geohashes: string[] = [];
  const scores: number[] = [];
  const bounds: number[][] = [];
  const indexes = cellsInBbox(matrix, bbox);
  if (precision === 6) {
    for (const i of indexes) {
      const score = composites[i];
      if (Number.isNaN(score)) continue;
      geohashes.push(matrix.geohashes[i]);
      scores.push(round1(score));
      bounds.push([...matrix.bounds.subarray(i * 4, i * 4 + 4)]);
    }
    return { geohashes, scores, bounds };
  }
  const groups = new Map<string, { sum: number; n: number }>();
  for (const i of indexes) {
    const score = composites[i];
    if (Number.isNaN(score)) continue;
    const parent = matrix.geohashes[i].slice(0, 5);
    const group = groups.get(parent);
    if (group) {
      group.sum += score;
      group.n += 1;
    } else groups.set(parent, { sum: score, n: 1 });
  }
  for (const parent of [...groups.keys()].sort()) {
    const group = groups.get(parent)!;
    const b = decodeBounds(parent);
    if (!b) continue;
    geohashes.push(parent);
    scores.push(round1(group.sum / group.n));
    bounds.push([b.minLon, b.minLat, b.maxLon, b.maxLat]);
  }
  return { geohashes, scores, bounds };
}
