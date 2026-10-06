import { describe, expect, it, vi } from "vitest";

import { jsonResponse } from "@/test/fixtures";

import { createApiClient, parseTriangulate } from "./client";
import { ApiError } from "./errors";

const BASE_URL = "http://api.test/v1";

const polygon = {
  type: "MultiPolygon",
  coordinates: [[[[-74, 40], [-73.9, 40], [-73.9, 40.1], [-74, 40]]]],
};
const shape = {
  label: "Work",
  mode: "transit",
  minutes: 20,
  method: "network",
  cellCount: 12,
  areaSqMi: 3.5,
  geometry: polygon,
};

describe("parseTriangulate", () => {
  it("parses results, per-anchor areas and the overlap", () => {
    const parsed = parseTriangulate({
      results: [
        { geoEntityId: "x", address: "40.1,-73.9", latitude: 40.1, longitude: -73.9, compositeScore: 71 },
      ],
      isochrones: [shape],
      combined: { ...shape, label: null, geometry: null, cellCount: 0 },
    });
    expect(parsed.results).toEqual([{ lat: 40.1, lon: -73.9, score: 71, address: "40.1,-73.9" }]);
    expect(parsed.isochrones[0]).toMatchObject({ label: "Work", mode: "transit", cellCount: 12 });
    expect(parsed.combined?.geometry).toBeNull();
  });

  it("treats a missing combined area as null", () => {
    expect(parseTriangulate({ results: [] })).toEqual({ results: [], isochrones: [], combined: null });
  });

  it("rejects a malformed body", () => {
    expect(() => parseTriangulate(null)).toThrow(ApiError);
    expect(() => parseTriangulate({})).toThrow(ApiError);
    expect(() => parseTriangulate({ results: [{ latitude: "x" }] })).toThrow(ApiError);
    expect(() =>
      parseTriangulate({ results: [], isochrones: [{ ...shape, method: "magic" }] }),
    ).toThrow(ApiError);
  });
});

describe("triangulate", () => {
  it("posts the anchors as an intersect request", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => jsonResponse({ results: [] }));
    const client = createApiClient({ baseUrl: BASE_URL, fetch: fetchMock });

    await client.triangulate([
      { label: "Home", lat: 40.7, lon: -74, mode: "drive", minutes: 15 },
      { label: "Work", lat: 40.8, lon: -73.9, mode: "transit", minutes: 20 },
    ]);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${BASE_URL}/triangulate`);
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual({
      anchors: [
        { label: "Home", latitude: 40.7, longitude: -74, mode: "drive", maxTravelMinutes: 15 },
        { label: "Work", latitude: 40.8, longitude: -73.9, mode: "transit", maxTravelMinutes: 20 },
      ],
      combineMode: "intersect",
      limit: 50,
    });
  });

  it("rejects an invalid response with invalid-response", async () => {
    const client = createApiClient({
      baseUrl: BASE_URL,
      fetch: vi.fn<typeof fetch>(async () => jsonResponse({ nope: true })),
    });
    await expect(client.triangulate([])).rejects.toMatchObject({ kind: "invalid-response" });
  });
});
