import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Viewport } from "@/components/map/MapCanvas";
import type { ApiClient } from "@/lib/api/client";
import { createSelection, ALL_FACTORS } from "@/lib/map/selection";
import { encodeScoreFile } from "@/lib/scores/encode";
import { stubClient } from "@/test/fixtures";

import { useMapData } from "./useMapData";

const API_ORDER = [
  "grocery", "gym", "cafe", "restaurant", "bar", "shopping", "gasConvenience",
  "transit", "school", "traffic", "emergencyCorridor", "airport", "recreation",
];
const row = (geohash: string, grocery: number, transit: number) => ({
  geohash,
  scores: API_ORDER.map((k) => (k === "grocery" ? grocery : k === "transit" ? transit : null)),
});
const viewport: Viewport = {
  user: true,
  bbox: [-74.1, 40.6, -73.9, 40.8],
  zoom: 12,
  center: { lat: 40.7, lon: -74 },
};

function client(over: Partial<ApiClient>): ApiClient {
  return stubClient({
    getMapTop: vi.fn(async () => ({
      factors: [],
      weights: {},
      weightsVersion: "v",
      results: [],
    })),
    ...over,
  });
}

describe("useMapData with the score file", () => {
  it("recolours locally on a filter change without calling /map/cells", async () => {
    // Until the file arrives the API paints the map; afterwards it is not asked again.
    const getMapCells = vi.fn(async () => ({
      precision: 6, factors: [], weights: {}, weightsVersion: "v", truncated: false,
      geohashes: ["dr5ru0"], scores: [1],
    }));
    const c = client({
      getMapCells,
      getMapScores: async () =>
        encodeScoreFile(API_ORDER, [row("dr5ru0", 100, 0), row("dr5ru1", 0, 100)]),
    });
    const { result, rerender } = renderHook(
      ({ selection }) =>
        useMapData({ client: c, selection, viewport, topViewport: viewport }),
      { initialProps: { selection: ALL_FACTORS } },
    );
    await waitFor(() => expect(result.current.local).toBe(true));
    getMapCells.mockClear();
    const byHash = () =>
      Object.fromEntries(
        result.current.features.features.map((f) => [f.properties.geohash, f.properties.score]),
      );
    expect(byHash()).toEqual({ dr5ru0: 50, dr5ru1: 50 });
    act(() => rerender({ selection: createSelection(["grocery"]) }));
    expect(byHash()).toEqual({ dr5ru0: 100, dr5ru1: 0 });
    expect(result.current.topResults?.[0].geohash).toBe("dr5ru0");
    expect(getMapCells).not.toHaveBeenCalled();
  });

  it("asks the API for area names once, not on every filter change", async () => {
    const result1 = (geohash: string) => ({
      geohash, latitude: 40.7, longitude: -74, score: 50, metroArea: "NYC",
      subScores: {}, neighborhood: `Name ${geohash}`,
    });
    const getMapTop = vi.fn(async () => ({
      factors: [], weights: {}, weightsVersion: "v",
      results: [result1("dr5ru0"), result1("dr5ru1")],
    }));
    const c = client({
      getMapTop: getMapTop as unknown as ApiClient["getMapTop"],
      getMapScores: async () =>
        encodeScoreFile(API_ORDER, [row("dr5ru0", 100, 0), row("dr5ru1", 0, 100)]),
    });
    const { result, rerender } = renderHook(
      ({ selection }) =>
        useMapData({ client: c, selection, viewport, topViewport: viewport }),
      { initialProps: { selection: ALL_FACTORS } },
    );
    await waitFor(() => expect(result.current.topResults?.[0]?.neighborhood).toBe("Name dr5ru0"));
    const calls = getMapTop.mock.calls.length;
    act(() => rerender({ selection: createSelection(["transit"]) }));
    expect(result.current.topResults?.[0].geohash).toBe("dr5ru1");
    expect(result.current.topResults?.[0].neighborhood).toBe("Name dr5ru1");
    expect(getMapTop.mock.calls.length).toBe(calls);
  });

  it("falls back to the API when the file cannot be loaded", async () => {
    const getMapCells = vi.fn(async () => ({
      precision: 6,
      factors: [],
      weights: {},
      weightsVersion: "v",
      truncated: false,
      geohashes: ["dr5ru0"],
      scores: [42],
    }));
    const c = client({
      getMapCells,
      getMapScores: async () => new ArrayBuffer(3),
    });
    const { result } = renderHook(() =>
      useMapData({ client: c, selection: ALL_FACTORS, viewport, topViewport: viewport }),
    );
    await waitFor(() => expect(result.current.features.features).toHaveLength(1));
    expect(result.current.local).toBe(false);
    expect(result.current.features.features[0].properties.score).toBe(42);
  });
});
