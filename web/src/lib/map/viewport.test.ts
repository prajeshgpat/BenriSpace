import { describe, expect, it } from "vitest";

import { INITIAL_ZOOM_IN_LEVELS, initialMetroView, padBbox, precisionForZoom, roundBbox } from "./viewport";

describe("precisionForZoom", () => {
  it("uses ~5 km cells below zoom 10 and ~1 km cells from zoom 10", () => {
    expect(precisionForZoom(6)).toBe(5);
    expect(precisionForZoom(9.99)).toBe(5);
    expect(precisionForZoom(10)).toBe(6);
    expect(precisionForZoom(14)).toBe(6);
  });
});

describe("padBbox", () => {
  it("grows each side by the ratio of the box size", () => {
    expect(padBbox([-74, 40, -73, 41], 0.1)).toEqual([
      -74.1, 39.9, -72.9, 41.1,
    ]);
  });

  it("stays inside the world", () => {
    expect(padBbox([-179.9, -89.9, 179.9, 89.9], 0.5)).toEqual([
      -180, -90, 180, 90,
    ]);
  });
});

describe("roundBbox", () => {
  it("rounds so a sub-pixel pan keeps the same key", () => {
    expect(roundBbox([-74.00041, 40.00049, -73.0004, 41.00051])).toEqual([
      -74, 40, -73, 41.001,
    ]);
  });
});

describe("initialMetroView", () => {
  it("centres on New York City, four levels closer than the fitted zoom", () => {
    expect(INITIAL_ZOOM_IN_LEVELS).toBe(4);
    expect(initialMetroView(6.5)).toEqual({ lat: 40.73, lon: -73.99, zoom: 10.5 });
  });
});
