import { describe, expect, it } from "vitest";

import { cellsToFeatures, scoreRange } from "./features";
import { decodeBounds } from "./geohash";

describe("cellsToFeatures", () => {
  it("builds a closed rectangle per cell from its geohash bounds, with its score", () => {
    const { features } = cellsToFeatures({
      geohashes: ["dr5ru7"],
      scores: [87.5],
    });
    const bounds = decodeBounds("dr5ru7")!;

    expect(features).toHaveLength(1);
    expect(features[0].properties).toEqual({ geohash: "dr5ru7", score: 87.5 });
    const ring = features[0].geometry.coordinates[0];
    expect(ring).toHaveLength(5);
    expect(ring[0]).toEqual(ring[4]);
    expect(ring[0]).toEqual([bounds.minLon, bounds.minLat]);
    expect(ring[2]).toEqual([bounds.maxLon, bounds.maxLat]);
  });

  it("pairs geohashes and scores by index", () => {
    const { features } = cellsToFeatures({
      geohashes: ["dr5ru7", "dr5ru6"],
      scores: [10, 20],
    });
    expect(features.map((f) => f.properties.score)).toEqual([10, 20]);
  });

  it("drops cells with an undecodable geohash instead of failing", () => {
    const { features } = cellsToFeatures({
      geohashes: ["dr5ru7", "!!!"],
      scores: [1, 2],
    });
    expect(features).toHaveLength(1);
  });

  it("handles no cells", () => {
    expect(cellsToFeatures({ geohashes: [], scores: [] }).features).toEqual([]);
  });
});

describe("scoreRange", () => {
  it("finds the min and max present", () => {
    expect(scoreRange([40, 12.5, 97, 60])).toEqual({ min: 12.5, max: 97 });
  });

  it("is null when empty", () => {
    expect(scoreRange([])).toBeNull();
  });

  it("copes with very large arrays", () => {
    const scores = Array.from({ length: 200_000 }, (_, i) => i % 101);
    expect(scoreRange(scores)).toEqual({ min: 0, max: 100 });
  });
});
