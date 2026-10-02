import { describe, expect, it } from "vitest";

import {
  formatDistance,
  formatMiles,
  toFeet,
  toMiles,
} from "./units";

describe("units", () => {
  it("converts metres", () => {
    expect(toMiles(1609.344)).toBeCloseTo(1, 6);
    expect(toFeet(1609.344)).toBeCloseTo(5280, 6);
  });

  it("uses feet rounded to 50 under 0.1 mi", () => {
    expect(formatDistance(0)).toBe("0 ft");
    expect(formatDistance(137)).toBe("450 ft");
    expect(formatDistance(10)).toBe("50 ft");
    expect(formatDistance(160.5)).toBe("550 ft");
  });

  it("switches to miles at 0.1 mi", () => {
    expect(formatDistance(160.9344)).toBe("0.1 mi");
    expect(formatDistance(644)).toBe("0.4 mi");
    expect(formatDistance(1609.344)).toBe("1.0 mi");
    expect(formatDistance(16093.44)).toBe("10.0 mi");
  });

  it("formats miles directly", () => {
    expect(formatMiles(0.04)).toBe("200 ft");
    expect(formatMiles(0.6)).toBe("0.6 mi");
  });
});
