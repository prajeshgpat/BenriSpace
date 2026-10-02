import { describe, expect, it } from "vitest";

import { isInCoverage, roundPosition } from "./geolocation";

describe("isInCoverage", () => {
  it("accepts the metro and rejects other places", () => {
    expect(isInCoverage({ lat: 40.7492, lon: -73.985 })).toBe(true);
    expect(isInCoverage({ lat: 42.36, lon: -71.06 })).toBe(false);
    expect(isInCoverage({ lat: 39.1, lon: -94.58 })).toBe(false);
  });

  it("includes the edges", () => {
    expect(isInCoverage({ lat: 39.85, lon: -75.2 })).toBe(true);
    expect(isInCoverage({ lat: 42.0, lon: -71.85 })).toBe(true);
  });
});

describe("roundPosition", () => {
  it("keeps about 11 metres of precision", () => {
    expect(roundPosition({ lat: 40.749183, lon: -73.985029 })).toEqual({
      lat: 40.7492,
      lon: -73.985,
    });
  });
});
