import { describe, expect, it } from "vitest";
import type { AreaGeometry } from "@/lib/api/types";

import { originBounds, pointsAndAreasBounds, previewBounds } from "./preview";

describe("previewBounds", () => {
  it("fits both places when they are close", () => {
    const [w, s, e, n] = previewBounds({ lat: 40.75, lon: -73.98 }, { lat: 40.76, lon: -73.97 });
    expect(w).toBeLessThan(-73.98);
    expect(e).toBeGreaterThan(-73.97);
    expect(s).toBeLessThan(40.75);
    expect(n).toBeGreaterThan(40.76);
  });

  it("fits only the preview when the origin is far away", () => {
    const [w, , e] = previewBounds({ lat: 40.75, lon: -73.98 }, { lat: 40.9, lon: -73.5 });
    expect(w).toBeGreaterThan(-74);
    expect(e).toBeLessThan(-73.96);
  });
});

describe("originBounds", () => {
  it("wraps the polygon", () => {
    const geometry: AreaGeometry = {
      type: "Polygon",
      coordinates: [[[-74, 40], [-73.9, 40], [-73.9, 40.1], [-74, 40]]],
    };
    expect(originBounds({ lat: 40.05, lon: -73.95 }, geometry)).toEqual([-74, 40, -73.9, 40.1]);
  });
});

describe("pointsAndAreasBounds", () => {
  const square: AreaGeometry = {
    type: "Polygon",
    coordinates: [
      [
        [-74.2, 40.6],
        [-73.9, 40.6],
        [-73.9, 40.9],
        [-74.2, 40.9],
        [-74.2, 40.6],
      ],
    ],
  };

  it("covers every point and every area, skipping missing ones", () => {
    expect(
      pointsAndAreasBounds([{ lat: 41.0, lon: -73.5 }], [square, null, undefined]),
    ).toEqual([-74.2, 40.6, -73.5, 41.0]);
  });

  it("is null with nothing to show", () => {
    expect(pointsAndAreasBounds([], [null])).toBeNull();
  });
});
