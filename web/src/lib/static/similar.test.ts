import { describe, expect, it } from "vitest";

import { decodeAreaScores, areaSubScores } from "./areaScores";
import { compass, localSimilar, similarityOf } from "./similar";
import { buildAreaFile } from "./testing";

/**
 * Metro 0 has five areas that differ only in grocery (g) and restaurant (r);
 * every other factor is 50 everywhere, so its std is 0 and it adds nothing.
 *
 *   id  g   r
 *   1   10  10   <- the source
 *   2   20  10
 *   3   10  40
 *   4   50  50
 *   5   90  90
 *
 * By hand: mean g = 36, population std = sqrt(944) = 30.7246; mean r = 40,
 * std = sqrt(880) = 29.6648. Distances from area 1 (z units):
 *   2: 10/30.7246                         = 0.3255
 *   3: 30/29.6648                         = 1.0113
 *   4: sqrt((40/30.7246)^2 + (40/29.6648)^2) = 1.8744
 *   5: sqrt((80/30.7246)^2 + (80/29.6648)^2) = 3.7487
 * similarity = floor(100 * (1 - d / 6) + 0.5): 95, 83, 69, 38.
 * Area 6 is in another metro and looks identical to area 1; it must not appear.
 * Areas sit 0.1 degree of latitude (6.9 mi) apart on one meridian.
 */
const FIXTURE = [
  { id: 1, g: 10, r: 10, name: 65535 },
  { id: 2, g: 20, r: 10, name: 0 },
  { id: 3, g: 10, r: 40, name: 1 },
  { id: 4, g: 50, r: 50, name: 65535 },
  { id: 5, g: 90, r: 90, name: 65535 },
].map((a, i) => ({
  id: a.id,
  lat: 40.7 + i * 0.1,
  lon: -74,
  name: a.name,
  metro: 0,
  scores: { grocery: a.g, restaurant: a.r },
}));
FIXTURE.push({
  id: 6,
  lat: 40.7,
  lon: -74.001,
  name: 65535,
  metro: 1,
  scores: { grocery: 10, restaurant: 10 },
});

const areas = decodeAreaScores(
  buildAreaFile(FIXTURE, { names: ["Park Slope, Brooklyn", "Astoria, Queens"], metros: ["nyc", "la"] }),
);
const source = areaSubScores(areas, 0);
const base = { lat: 40.7, lon: -74, source, areaId: 1 };

describe("localSimilar", () => {
  it("ranks the metro's other areas by z-scored L2 distance and leaves the other metro out", () => {
    const result = localSimilar(areas, base)!;
    expect(result.results.map((r) => r.latitude)).toEqual([40.8, 40.9, 41, 41.1]);
    expect(result.results.map((r) => r.similarity)).toEqual([95, 83, 69, 38]);
    expect(result.minSeparationMi).toBe(1);
    expect(result.priorities).toHaveLength(13);
  });

  it("returns the UI's shape: names, direction, distance, differences, summary", () => {
    const [first, second, third] = localSimilar(areas, base)!.results;
    expect(first).toMatchObject({
      neighborhood: "Park Slope, Brooklyn",
      direction: "N",
      distanceLabel: "6.9 mi",
      areaLabel: null,
      differences: [{ factor: "grocery", label: "grocery", delta: 10 }],
      summary: "10 points better for grocery.",
    });
    expect(second.neighborhood).toBe("Astoria, Queens");
    expect(second.differences).toEqual([{ factor: "restaurant", label: "restaurants", delta: 30 }]);
    // Equal gaps keep factor order.
    expect(third.differences.map((d) => d.factor)).toEqual(["grocery", "restaurant"]);
    expect(third.neighborhood).toBeNull();
    // Stored composite: (14*20 + 10*10 + 82*50) / 106 = 42.26.
    expect(first.compositeScore).toBe(42);
  });

  it("falls back to the nearest area centre when the id is unknown", () => {
    const result = localSimilar(areas, { ...base, areaId: undefined })!;
    expect(result.results[0].latitude).toBe(40.8);
  });

  it("spreads results out and keeps them clear of the point", () => {
    const result = localSimilar(areas, { ...base, minSeparationMi: 10 })!;
    // Area 2 is 6.9 mi away (too close); 3 is kept; 4 is 6.9 mi from 3; 5 is kept.
    expect(result.results.map((r) => r.latitude)).toEqual([40.9, 41.1]);
  });

  it("honours k", () => {
    expect(localSimilar(areas, { ...base, k: 2 })!.results).toHaveLength(2);
  });

  it("re-ranks on the selected factors with weights scaled to sum 13", () => {
    // Grocery only: distance = sqrt(13) * |dz_g|. Area 3 matches (0), then 2, 4, 5.
    const result = localSimilar(areas, { ...base, factors: ["grocery"] })!;
    expect(result.results.map((r) => r.latitude)).toEqual([40.9, 40.8, 41, 41.1]);
    // sqrt(13) * 0.3255 = 1.1735 -> 80; area 4: sqrt(13) * 1.3019 = 4.694 -> 22; area 5 is past the cut-off.
    expect(result.results.map((r) => r.similarity)).toEqual([100, 80, 22, 0]);
    // Differences cover only the selected factors: area 3 differs on restaurant only.
    expect(result.results[0].differences).toEqual([]);
    expect(result.results[0].summary).toBe("Very similar across all factors.");
    expect(result.priorities).toEqual(["grocery"]);
  });

  it("returns null when the file cannot place the source", () => {
    const none = decodeAreaScores(buildAreaFile([{ id: 1, lat: 40, lon: -74, metro: 255 }]));
    expect(localSimilar(none, { ...base, areaId: 1 })).toBeNull();
    expect(localSimilar(decodeAreaScores(buildAreaFile([])), base)).toBeNull();
  });

  it("treats a missing score as the metro average", () => {
    const withGap = decodeAreaScores(
      buildAreaFile([
        { id: 1, lat: 40.7, lon: -74, scores: { grocery: 0, restaurant: 100 } },
        { id: 2, lat: 40.8, lon: -74, scores: { grocery: 255, restaurant: 100 } },
        { id: 3, lat: 40.9, lon: -74, scores: { grocery: 100, restaurant: 100 } },
      ]),
    );
    // Grocery mean over non-null = 50, std 50: z = -1, 1; the gap counts as 0.
    // Source z_g = -1: area 2 (0) is 1 away, area 3 (+1) is 2 away.
    const result = localSimilar(withGap, {
      lat: 40.7,
      lon: -74,
      areaId: 1,
      source: areaSubScores(withGap, 0),
    })!;
    expect(result.results.map((r) => r.latitude)).toEqual([40.8, 40.9]);
    expect(result.results.map((r) => r.similarity)).toEqual([83, 67]);
  });
});

describe("helpers", () => {
  it("similarity is 100 at 0, 0 at the max distance, rounded half up", () => {
    expect(similarityOf(0)).toBe(100);
    expect(similarityOf(6)).toBe(0);
    expect(similarityOf(9)).toBe(0);
    expect(similarityOf(3)).toBe(50);
  });
  it("compass matches the server's 8 points", () => {
    expect(compass(40, -74, 41, -74)).toBe("N");
    expect(compass(40, -74, 40, -73)).toBe("E");
    expect(compass(40, -74, 39, -74)).toBe("S");
    expect(compass(40, -74, 40, -75)).toBe("W");
    expect(compass(40, -74, 41, -73)).toBe("NE");
    expect(compass(40, -74, 39, -75)).toBe("SW");
  });
});
