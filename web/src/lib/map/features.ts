import type { Feature, FeatureCollection, Polygon } from "geojson";

import type { MapCells } from "@/lib/api/types";

import { decodeBounds } from "./geohash";

export interface CellProperties {
  geohash: string;
  score: number;
}

export type CellFeatureCollection = FeatureCollection<Polygon, CellProperties>;

export const EMPTY_CELLS: CellFeatureCollection = {
  type: "FeatureCollection",
  features: [],
};

/**
 * Each cell becomes a rectangle decoded from its geohash. Cells with an
 * undecodable hash are dropped rather than failing the whole viewport.
 */
export function cellsToFeatures(
  cells: Pick<MapCells, "geohashes" | "scores">,
): CellFeatureCollection {
  const features: Feature<Polygon, CellProperties>[] = [];
  cells.geohashes.forEach((geohash, index) => {
    const bounds = decodeBounds(geohash);
    if (!bounds) return;
    const { minLon, minLat, maxLon, maxLat } = bounds;
    features.push({
      type: "Feature",
      properties: { geohash, score: cells.scores[index] },
      geometry: {
        type: "Polygon",
        coordinates: [
          [
            [minLon, minLat],
            [maxLon, minLat],
            [maxLon, maxLat],
            [minLon, maxLat],
            [minLon, minLat],
          ],
        ],
      },
    });
  });
  return { type: "FeatureCollection", features };
}

/**
 * Same rectangles as `cellsToFeatures`, from bounds that are already known
 * (minLon, minLat, maxLon, maxLat), so a recolour does not decode geohashes again.
 */
export function boundsToFeatures(cells: {
  geohashes: readonly string[];
  scores: readonly number[];
  bounds: readonly (readonly number[])[];
}): CellFeatureCollection {
  return {
    type: "FeatureCollection",
    features: cells.geohashes.map((geohash, index) => {
      const [minLon, minLat, maxLon, maxLat] = cells.bounds[index];
      return {
        type: "Feature",
        properties: { geohash, score: cells.scores[index] },
        geometry: {
          type: "Polygon",
          coordinates: [
            [
              [minLon, minLat],
              [maxLon, minLat],
              [maxLon, maxLat],
              [minLon, maxLat],
              [minLon, minLat],
            ],
          ],
        },
      };
    }),
  };
}

export interface ScoreRange {
  min: number;
  max: number;
}

export function scoreRange(scores: readonly number[]): ScoreRange | null {
  if (scores.length === 0) return null;
  let min = Infinity;
  let max = -Infinity;
  for (const score of scores) {
    if (score < min) min = score;
    if (score > max) max = score;
  }
  return { min, max };
}
