import { describe, expect, it } from "vitest";

import { decodeBounds } from "./geohash";

describe("decodeBounds", () => {
  it("decodes the Wikipedia example ezs42 to its published rectangle", () => {
    const bounds = decodeBounds("ezs42")!;

    expect(bounds.minLat).toBeCloseTo(42.58300781, 6);
    expect(bounds.maxLat).toBeCloseTo(42.62695313, 6);
    expect(bounds.minLon).toBeCloseTo(-5.625, 6);
    expect(bounds.maxLon).toBeCloseTo(-5.58105469, 6);
  });

  it("splits the globe into the known single-character quadrants", () => {
    expect(decodeBounds("s")).toEqual({
      minLat: 0,
      maxLat: 45,
      minLon: 0,
      maxLon: 45,
    });
    expect(decodeBounds("0")).toEqual({
      minLat: -90,
      maxLat: -45,
      minLon: -180,
      maxLon: -135,
    });
    expect(decodeBounds("z")).toEqual({
      minLat: 45,
      maxLat: 90,
      minLon: 135,
      maxLon: 180,
    });
  });

  it("places Manhattan in dr5r", () => {
    const bounds = decodeBounds("dr5ru")!;
    // Midtown Manhattan (40.7484, -73.9857) is inside the dr5ru cell.
    expect(bounds.minLat).toBeLessThan(40.7484);
    expect(bounds.maxLat).toBeGreaterThan(40.7484);
    expect(bounds.minLon).toBeLessThan(-73.9857);
    expect(bounds.maxLon).toBeGreaterThan(-73.9857);
  });

  it("matches the documented cell sizes for precision 5 and 6", () => {
    const five = decodeBounds("dr5ru")!;
    expect(five.maxLon - five.minLon).toBeCloseTo(360 / 2 ** 13, 9);
    expect(five.maxLat - five.minLat).toBeCloseTo(180 / 2 ** 12, 9);

    const six = decodeBounds("dr5rus")!;
    expect(six.maxLon - six.minLon).toBeCloseTo(360 / 2 ** 15, 9);
    expect(six.maxLat - six.minLat).toBeCloseTo(180 / 2 ** 15, 9);
  });

  it("nests: a longer hash lies inside its prefix", () => {
    const parent = decodeBounds("dr5ru")!;
    const child = decodeBounds("dr5rus")!;
    expect(child.minLat).toBeGreaterThanOrEqual(parent.minLat);
    expect(child.maxLat).toBeLessThanOrEqual(parent.maxLat);
    expect(child.minLon).toBeGreaterThanOrEqual(parent.minLon);
    expect(child.maxLon).toBeLessThanOrEqual(parent.maxLon);
  });

  it("is case-insensitive and rejects invalid input", () => {
    expect(decodeBounds("DR5RU")).toEqual(decodeBounds("dr5ru"));
    expect(decodeBounds("")).toBeNull();
    expect(decodeBounds("dr5ra")).toBeNull();
  });
});
