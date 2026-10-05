import { describe, expect, it } from "vitest";

import { decodeAreaScores } from "./areaScores";
import { provisionalArea } from "./provisional";
import { buildAreaFile } from "./testing";

const areas = decodeAreaScores(
  buildAreaFile(
    [
      { id: 10, lat: 40.7, lon: -74, name: 0, scores: { grocery: 80, restaurant: 40, cafe: 255 } },
      { id: 20, lat: 40.8, lon: -74, scores: { grocery: 255, restaurant: 255 } },
    ],
    { names: ["Park Slope, Brooklyn"] },
  ),
);

describe("provisionalArea", () => {
  it("normalises the composite to the selected factors (default weights 14 and 10)", () => {
    const got = provisionalArea(areas, 10, ["grocery", "restaurant"], undefined)!;
    // (14*80 + 10*40) / 24 = 63.3
    expect(got.compositeScore).toBe(63.3);
    expect(got.neighborhood).toBe("Park Slope, Brooklyn");
    expect(got.subScores.grocery).toBe(80);
    expect(got.subScores.cafe).toBeNull();
  });

  it("uses the caller's weights and skips factors with no score", () => {
    expect(provisionalArea(areas, 10, ["grocery", "restaurant"], { grocery: 1, restaurant: 3 })!.compositeScore).toBe(50);
    // cafe has no score there, so only grocery counts.
    expect(provisionalArea(areas, 10, ["grocery", "cafe"], undefined)!.compositeScore).toBe(80);
  });

  it("is null for an unknown id or when no selected factor has a score", () => {
    expect(provisionalArea(areas, 99, ["grocery"], undefined)).toBeNull();
    expect(provisionalArea(areas, 20, ["grocery", "restaurant"], undefined)).toBeNull();
    expect(provisionalArea(areas, 10, [], undefined)).toBeNull();
  });
});
