/**
 * Joining the score file to vector tiles. The tiles hold geometry and a `g`
 * (geohash) property only; each cell's colour is a feature-state `score`
 * set from the locally computed composites. These helpers decide which states
 * change, so a filter change touches only the cells whose score moved.
 */

export type TileScores = ReadonlyMap<string, number>;

/** Which tile layer draws a geohash precision. */
export const TILE_LAYER_FOR_PRECISION = { 5: "parents", 6: "cells" } as const;

export interface TileCells {
  precision: 5 | 6;
  geohashes: readonly string[];
  scores: readonly number[];
}

export function tileScoresOf(cells: TileCells): Map<string, number> {
  const out = new Map<string, number>();
  cells.geohashes.forEach((geohash, index) => out.set(geohash, cells.scores[index]));
  return out;
}

export interface TileStateDiff {
  set: [geohash: string, score: number][];
  remove: string[];
}

/** What to set and what to clear to turn `previous` into `next`. */
export function diffTileScores(previous: TileScores, next: TileScores): TileStateDiff {
  const set: TileStateDiff["set"] = [];
  for (const [geohash, score] of next) {
    if (previous.get(geohash) !== score) set.push([geohash, score]);
  }
  const remove: string[] = [];
  for (const geohash of previous.keys()) {
    if (!next.has(geohash)) remove.push(geohash);
  }
  return { set, remove };
}
