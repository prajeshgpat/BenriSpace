import { describe, expect, it } from "vitest";

import type { AreaGeometry, PlacePin, Position } from "@/lib/api/types";

import {
  clusterLabel,
  clusterScreenPoints,
  keyPins,
  pinFactors,
  pinLabel,
  placeSearch,
} from "./placePins";

function square(west: number, south: number, east: number, north: number): AreaGeometry {
  return {
    type: "Polygon",
    coordinates: [
      [
        [west, south],
        [east, south],
        [east, north],
        [west, north],
        [west, south],
      ],
    ],
  };
}

const pin = (over: Partial<PlacePin> = {}): PlacePin => ({
  factor: "restaurant",
  name: "Pasta",
  brand: null,
  category: "restaurant",
  latitude: 40.7,
  longitude: -73.9,
  distanceMi: 0.24,
  ...over,
});

describe("placeSearch", () => {
  const point = { lat: 40.7, lon: -73.9 };

  it("uses 0.5 mi around the point without an area", () => {
    expect(placeSearch(point, null)).toEqual({ ...point, radiusMi: 0.5 });
  });

  it("centres on the polygon bbox with half-diagonal plus margin", () => {
    // About 0.69 mi tall and 0.52 mi wide: half-diagonal ~0.43, plus 0.15.
    const result = placeSearch(point, square(-73.91, 40.695, -73.9, 40.705));
    expect(result.lat).toBeCloseTo(40.7, 4);
    expect(result.lon).toBeCloseTo(-73.905, 4);
    expect(result.radiusMi).toBeGreaterThan(0.5);
    expect(result.radiusMi).toBeLessThan(0.7);
  });

  it("clamps to 0.25 and 1.5 mi", () => {
    expect(placeSearch(point, square(-73.9, 40.7, -73.9, 40.7)).radiusMi).toBe(0.25);
    expect(placeSearch(point, square(-74.2, 40.4, -73.6, 41)).radiusMi).toBe(1.5);
  });

  it("handles a MultiPolygon", () => {
    const ring = (g: AreaGeometry) => (g as { coordinates: Position[][] }).coordinates;
    const geometry: AreaGeometry = {
      type: "MultiPolygon",
      coordinates: [
        ring(square(-73.91, 40.69, -73.9, 40.7)),
        ring(square(-73.9, 40.7, -73.89, 40.71)),
      ],
    };
    expect(placeSearch(point, geometry).lon).toBeCloseTo(-73.9, 4);
  });
});

describe("clusterScreenPoints", () => {
  const pt = (x: number, y: number) => ({ x, y });

  it("merges points within the radius and keeps far ones apart", () => {
    const clusters = clusterScreenPoints([pt(0, 0), pt(10, 5), pt(200, 200), pt(205, 198)], 40);
    expect(clusters.map((c) => c.members.length)).toEqual([2, 2]);
    expect(clusters[0].x).toBeCloseTo(5);
    expect(clusters[0].y).toBeCloseTo(2.5);
  });

  it("joins the nearest cluster and is deterministic", () => {
    const points = [pt(0, 0), pt(60, 0), pt(30, 0)];
    const first = clusterScreenPoints(points, 40);
    expect(first.map((c) => c.members.length)).toEqual([2, 1]);
    expect(clusterScreenPoints(points, 40)).toEqual(first);
  });

  it("returns singletons when nothing is close", () => {
    expect(clusterScreenPoints([pt(0, 0), pt(100, 0)], 40)).toHaveLength(2);
    expect(clusterScreenPoints([], 40)).toEqual([]);
  });
});

describe("labels", () => {
  it("summarises a cluster by factor, most common first", () => {
    const members = [
      ...Array.from({ length: 8 }, () => ({ factor: "restaurant" as const })),
      ...Array.from({ length: 4 }, () => ({ factor: "bar" as const })),
    ];
    expect(clusterLabel(members)).toBe("12 places: 8 restaurants, 4 bars");
    expect(clusterLabel([{ factor: "cafe" }, { factor: "bar" }])).toBe("2 places: 1 cafe, 1 bar");
  });

  it("labels a single pin with name, kind and distance", () => {
    expect(pinLabel(pin())).toBe("Pasta · Restaurant · 0.2 mi");
  });
});

describe("pins", () => {
  it("keeps only place-based selected factors in a stable order", () => {
    expect(pinFactors(["traffic", "bar", "airport", "grocery"])).toEqual(["grocery", "bar"]);
  });

  it("drops duplicates and caps the total", () => {
    expect(keyPins([pin(), pin(), pin({ name: "Other" })])).toHaveLength(2);
    const many = Array.from({ length: 200 }, (_, i) => pin({ name: `P${i}` }));
    expect(keyPins(many)).toHaveLength(150);
  });
});
