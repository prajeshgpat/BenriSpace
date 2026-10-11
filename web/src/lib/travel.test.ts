import { describe, expect, it } from "vitest";

import {
  defaultTravel,
  distanceMi,
  TRAVEL_OPTIONS,
  travelOption,
  tuneTravel,
  widerTravel,
} from "./travel";

describe("defaultTravel", () => {
  it("starts dense places on a 20 min train", () => {
    expect(defaultTravel("walk")).toEqual({ mode: "transit", minutes: 20 });
  });
  it("drives 15 min everywhere else", () => {
    for (const m of ["drive", null, undefined] as const) {
      expect(defaultTravel(m)).toEqual({ mode: "drive", minutes: 15 });
    }
  });
});

describe("travel options", () => {
  it("keeps the per-mode ranges and initial minutes", () => {
    expect(TRAVEL_OPTIONS.map((o) => [o.mode, o.initial, o.minutes.at(-1)])).toEqual([
      ["walk", 10, 45],
      ["transit", 20, 45],
      ["drive", 15, 60],
    ]);
    expect(travelOption("transit").label).toBe("Train");
  });
});

describe("tuneTravel", () => {
  const A = { lat: 40.75, lon: -73.99 };
  // About 0.2 mi, ~3 mi, ~13 mi and ~150 mi north of A.
  const at = (miles: number) => ({ lat: A.lat + miles / 69, lon: A.lon });

  it("walks when the places are close", () => {
    expect(distanceMi(A, at(0.2))).toBeCloseTo(0.2, 1);
    const tuned = tuneTravel([A, at(0.2)], "walk");
    expect(tuned?.mode).toBe("walk");
    expect(tuned?.minutes).toBeGreaterThanOrEqual(10);
    expect(tuned?.minutes).toBeLessThanOrEqual(20);
  });

  it("takes the train for far points in a dense place", () => {
    expect(tuneTravel([A, at(3)], "walk")?.mode).toBe("transit");
  });

  it("drives instead in a suburb, and never takes the train there", () => {
    expect(tuneTravel([A, at(3)], "drive")?.mode).toBe("drive");
    expect(tuneTravel([A, at(3)], null)?.mode).toBe("drive");
  });

  it("uses the farthest pair of several places", () => {
    const near = tuneTravel([A, at(0.2)], "drive")!;
    const spread = tuneTravel([A, at(0.2), at(10)], "drive")!;
    expect(spread.mode).toBe("drive");
    expect(spread.minutes).toBeGreaterThan(near.minutes);
  });

  it("gives null when the places are too far apart", () => {
    expect(tuneTravel([A, at(150)], "drive")).toBeNull();
    expect(tuneTravel([A, at(150)], "walk")).toBeNull();
  });
});

describe("widerTravel", () => {
  it("steps minutes up by 5 within the mode", () => {
    expect(widerTravel({ mode: "walk", minutes: 10 })).toEqual({ mode: "walk", minutes: 15 });
    expect(widerTravel({ mode: "drive", minutes: 55 })).toEqual({ mode: "drive", minutes: 60 });
  });

  it("switches to a faster mode once the minutes run out", () => {
    expect(widerTravel({ mode: "walk", minutes: 45 })).toEqual({ mode: "transit", minutes: 30 });
    expect(widerTravel({ mode: "transit", minutes: 45 })).toEqual({ mode: "drive", minutes: 30 });
  });

  it("has no step past a 60 min drive", () => {
    expect(widerTravel({ mode: "drive", minutes: 60 })).toBeNull();
  });
});

describe("distanceMi", () => {
  it("is zero for the same point and about 69 mi per degree of latitude", () => {
    expect(distanceMi({ lat: 40, lon: -74 }, { lat: 40, lon: -74 })).toBe(0);
    expect(distanceMi({ lat: 40, lon: -74 }, { lat: 41, lon: -74 })).toBeCloseTo(69, 0);
  });
});
