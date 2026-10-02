import { describe, expect, it } from "vitest";

import { needsReadableAddress } from "./reverseTarget";

const point = { kind: "coordinates" as const, lat: 40.7314, lon: -74.0635 };

describe("needsReadableAddress", () => {
  it("is true when the label is just the coordinates", () => {
    expect(needsReadableAddress({ ...point, label: "40.7314, -74.0635" })).toBe(true);
  });

  it("is true for a best-areas stand-in title", () => {
    expect(needsReadableAddress({ ...point, label: "Area near 40.731, -74.064" })).toBe(true);
  });

  it("is false when the point already has a name", () => {
    expect(needsReadableAddress({ ...point, label: "Your location" })).toBe(false);
    expect(needsReadableAddress({ ...point, label: "350 5th Ave, New York, NY" })).toBe(false);
  });

  it("is false for typed addresses and no target", () => {
    expect(needsReadableAddress({ kind: "address", address: "1 Main St" })).toBe(false);
    expect(needsReadableAddress(null)).toBe(false);
  });
});
