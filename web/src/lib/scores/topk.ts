import type { MapTopResult } from "@/lib/api/types";

import {
  cellsInBbox,
  round1,
  subScoresOf,
  type Bbox4,
  type ScoreMatrix,
} from "./matrix";

const EARTH_RADIUS_M = 6_371_000;
const METERS_PER_MILE = 1609.344;
const MILES_PER_DEGREE_LAT = 69.0;
/** Grid cells must never be narrower than the spacing anywhere in the metro. */
const WIDEST_LATITUDE = 42.5;

function haversineM(lat1: number, lon1: number, lat2: number, lon2: number) {
  const toRad = Math.PI / 180;
  const phi1 = lat1 * toRad;
  const phi2 = lat2 * toRad;
  const dPhi = (lat2 - lat1) * toRad;
  const dLambda = (lon2 - lon1) * toRad;
  const a =
    Math.sin(dPhi / 2) ** 2 +
    Math.cos(phi1) * Math.cos(phi2) * Math.sin(dLambda / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(a));
}

/**
 * Max-heap of cell indexes, best first: higher composite, then the smaller
 * geohash (the API's `order by score desc, geohash`). Built in O(n); each pop
 * is O(log n), so picking k winners costs O(n + k log n) rather than a sort.
 */
class CellHeap {
  private readonly items: Int32Array;
  private size: number;

  constructor(
    indexes: readonly number[],
    private readonly composites: Float64Array,
    private readonly geohashes: readonly string[],
  ) {
    this.items = Int32Array.from(indexes);
    this.size = indexes.length;
    for (let i = (this.size >> 1) - 1; i >= 0; i--) this.down(i);
  }

  private before(a: number, b: number): boolean {
    const sa = this.composites[a];
    const sb = this.composites[b];
    if (sa !== sb) return sa > sb;
    return this.geohashes[a] < this.geohashes[b];
  }

  private down(start: number) {
    const { items } = this;
    let i = start;
    for (;;) {
      const left = 2 * i + 1;
      const right = left + 1;
      let best = i;
      if (left < this.size && this.before(items[left], items[best])) best = left;
      if (right < this.size && this.before(items[right], items[best])) best = right;
      if (best === i) return;
      [items[i], items[best]] = [items[best], items[i]];
      i = best;
    }
  }

  pop(): number | null {
    if (this.size === 0) return null;
    const top = this.items[0];
    this.size -= 1;
    if (this.size > 0) {
      this.items[0] = this.items[this.size];
      this.down(0);
    }
    return top;
  }
}

export interface TopOptions {
  bbox?: Bbox4;
  limit: number;
  minSeparationMi: number;
}

/**
 * The best `limit` cells that are each at least `minSeparationMi` from every
 * cell already chosen: the same greedy walk as `api.mapdata.select_separated`,
 * but candidates come off a heap and the spacing test looks only at the
 * chosen cells in the 3 x 3 neighbouring grid squares (grid hash, O(1)).
 * Names are not known here; `neighborhood` is null until looked up.
 */
export function localTop(
  matrix: ScoreMatrix,
  composites: Float64Array,
  { bbox, limit, minSeparationMi }: TopOptions,
): MapTopResult[] {
  const inView = bbox
    ? cellsInBbox(matrix, bbox)
    : Array.from({ length: matrix.count }, (_, i) => i);
  const candidates = inView.filter((i) => !Number.isNaN(composites[i]));
  const heap = new CellHeap(candidates, composites, matrix.geohashes);

  const spacing = Math.max(minSeparationMi, 0);
  const latStep = spacing / MILES_PER_DEGREE_LAT;
  const lonStep =
    spacing / (MILES_PER_DEGREE_LAT * Math.cos((WIDEST_LATITUDE * Math.PI) / 180));
  const squares = new Map<string, number[]>();
  const keyOf = (la: number, lo: number): [number, number] =>
    spacing === 0 ? [0, 0] : [Math.floor(la / latStep), Math.floor(lo / lonStep)];

  const chosen: number[] = [];
  for (let i = heap.pop(); i !== null && chosen.length < limit; i = heap.pop()) {
    const la = matrix.lat[i];
    const lo = matrix.lon[i];
    const [row, col] = keyOf(la, lo);
    let clear = true;
    if (spacing > 0) {
      for (let dr = -1; dr <= 1 && clear; dr++) {
        for (let dc = -1; dc <= 1 && clear; dc++) {
          for (const j of squares.get(`${row + dr},${col + dc}`) ?? []) {
            if (
              haversineM(la, lo, matrix.lat[j], matrix.lon[j]) <
              spacing * METERS_PER_MILE
            ) {
              clear = false;
              break;
            }
          }
        }
      }
    }
    if (!clear) continue;
    chosen.push(i);
    const key = `${row},${col}`;
    const bucket = squares.get(key);
    if (bucket) bucket.push(i);
    else squares.set(key, [i]);
  }

  return chosen.map((i) => ({
    geohash: matrix.geohashes[i],
    latitude: Math.round(matrix.lat[i] * 1e5) / 1e5,
    longitude: Math.round(matrix.lon[i] * 1e5) / 1e5,
    score: round1(composites[i]),
    metroArea: "",
    subScores: subScoresOf(matrix, i),
    neighborhood: null,
  }));
}
