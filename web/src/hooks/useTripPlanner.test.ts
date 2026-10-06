import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AreaGeometry, Triangulation } from "@/lib/api/types";

import {
  NOT_FOUND_MESSAGE,
  TRIANGULATE_DEBOUNCE_MS,
  distanceMi,
  pickSpreadResults,
  useTripPlanner,
  type TripPlace,
} from "./useTripPlanner";

const PLACE: TripPlace = { label: "Home", lat: 40.7, lon: -74, travelMode: "walk" };
const SUBURB: TripPlace = { label: "Out", lat: 40.1, lon: -74.5, travelMode: "drive" };

const geometry: AreaGeometry = {
  type: "MultiPolygon",
  coordinates: [[[[-74, 40], [-73.9, 40], [-73.9, 40.1], [-74, 40]]]],
};
const iso = (cellCount = 4, method: "network" | "estimate" = "network") => ({
  label: null,
  mode: "drive" as const,
  minutes: 15,
  method,
  areaSqMi: 2,
  cellCount,
  geometry,
});

function body(overrides: Partial<Triangulation> = {}): Triangulation {
  return {
    results: [
      { lat: 40.71, lon: -73.99, score: 80, address: "40.7100,-73.9900" },
      { lat: 40.7101, lon: -73.9901, score: 79, address: "near duplicate" },
      { lat: 40.8, lon: -73.9, score: 70, address: "Some Street" },
    ],
    isochrones: [iso(), iso()],
    combined: iso(),
    ...overrides,
  };
}

function setup(place: TripPlace | null = PLACE) {
  const triangulate = vi.fn(async (): Promise<Triangulation> => body());
  const reverseGeocode = vi.fn(async () => ({ label: "12 Main St", latitude: 0, longitude: 0 }));
  const suggestAddresses = vi.fn(async () => [
    { label: "Park Ave, NY", latitude: 40.75, longitude: -73.97 },
  ]);
  const client = { triangulate, reverseGeocode, suggestAddresses } as never;
  const hook = renderHook(({ p }) => useTripPlanner(client, p), { initialProps: { p: place } });
  return { hook, triangulate, reverseGeocode, suggestAddresses };
}

const pick = { label: "Park Ave, NY", latitude: 40.75, longitude: -73.97 };

async function flush(ms = TRIANGULATE_DEBOUNCE_MS) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("useTripPlanner rows", () => {
  it("first click creates row 0 from the place plus Point 1 (dense: train 20)", () => {
    const { hook } = setup();
    expect(hook.result.current.canAdd).toBe(true);
    expect(hook.result.current.active).toBe(false);
    act(() => hook.result.current.add());
    const { rows } = hook.result.current;
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({ label: "Home", lat: 40.7, lon: -74, mode: "transit", minutes: 20 });
    expect(rows[1]).toMatchObject({ label: "", mode: "transit", minutes: 20 });
    expect(rows[1].lat).toBeUndefined();
    expect(hook.result.current.active).toBe(true);
    expect(hook.result.current.lastAddedId).toBe(rows[1].id);
  });

  it("defaults to drive 15 when the place is not dense", () => {
    const { hook } = setup(SUBURB);
    act(() => hook.result.current.add());
    expect(hook.result.current.rows.map((r) => [r.mode, r.minutes])).toEqual([
      ["drive", 15],
      ["drive", 15],
    ]);
  });

  it("allows a second point, then no more", () => {
    const { hook } = setup();
    act(() => hook.result.current.add());
    act(() => hook.result.current.add());
    expect(hook.result.current.rows).toHaveLength(3);
    expect(hook.result.current.canAdd).toBe(false);
    act(() => hook.result.current.add());
    expect(hook.result.current.rows).toHaveLength(3);
  });

  it("works without a scored place, leaving row 0 to fill in", () => {
    const { hook } = setup(null);
    expect(hook.result.current.canAdd).toBe(true);
    act(() => hook.result.current.add());
    expect(hook.result.current.rows[0].lat).toBeUndefined();
    expect(hook.result.current.canAdd).toBe(true);
  });

  it("freezes row 0 when the scored place changes", () => {
    const { hook } = setup();
    act(() => hook.result.current.add());
    hook.rerender({ p: SUBURB });
    expect(hook.result.current.rows[0]).toMatchObject({ label: "Home", lat: 40.7 });
    act(() => hook.result.current.setTravel(hook.result.current.rows[0].id, { mode: "walk", minutes: 10 }));
    expect(hook.result.current.rows[0]).toMatchObject({ mode: "walk", minutes: 10 });
  });

  it("removing row 0 or the last point removes the planner; a middle point just goes", () => {
    const { hook } = setup();
    act(() => hook.result.current.add());
    act(() => hook.result.current.remove(hook.result.current.rows[1].id));
    expect(hook.result.current.rows).toEqual([]);

    act(() => hook.result.current.add());
    act(() => hook.result.current.add());
    const [, first, second] = hook.result.current.rows;
    act(() => hook.result.current.remove(first.id));
    expect(hook.result.current.rows.map((r) => r.id)).toContain(second.id);
    expect(hook.result.current.rows).toHaveLength(2);

    act(() => hook.result.current.remove(hook.result.current.rows[0].id));
    expect(hook.result.current.rows).toEqual([]);
  });
});

describe("useTripPlanner address resolution", () => {
  it("resolves typed text through suggestAddresses with limit 1", async () => {
    const { hook, suggestAddresses } = setup();
    act(() => hook.result.current.add());
    const id = hook.result.current.rows[1].id;
    await act(async () => hook.result.current.submitText(id, "park ave"));
    expect(suggestAddresses).toHaveBeenCalledWith("park ave", { limit: 1 });
    expect(hook.result.current.rows[1]).toMatchObject({ label: "Park Ave, NY", lat: 40.75, error: null });
  });

  it("shows the not-found message when nothing matches", async () => {
    const { hook, suggestAddresses } = setup();
    suggestAddresses.mockResolvedValueOnce([]);
    act(() => hook.result.current.add());
    const id = hook.result.current.rows[1].id;
    await act(async () => hook.result.current.submitText(id, "zzzz"));
    expect(hook.result.current.rows[1].error).toBe(NOT_FOUND_MESSAGE);
    act(() => hook.result.current.selectSuggestion(id, pick));
    expect(hook.result.current.rows[1].error).toBeNull();
  });

  it("clearing a place drops its coordinates", () => {
    const { hook } = setup();
    act(() => hook.result.current.add());
    act(() => hook.result.current.clearPlace(hook.result.current.rows[0].id));
    expect(hook.result.current.rows[0]).toMatchObject({ label: "", lat: undefined, lon: undefined });
  });
});

describe("useTripPlanner triangulation", () => {
  it("does not call the API with fewer than two placed rows", async () => {
    const { hook, triangulate } = setup();
    act(() => hook.result.current.add());
    await flush(2000);
    expect(triangulate).not.toHaveBeenCalled();
    expect(hook.result.current.status).toBe("idle");
  });

  it("waits 400 ms after the last change, then calls once", async () => {
    const { hook, triangulate } = setup();
    act(() => hook.result.current.add());
    const id = hook.result.current.rows[1].id;
    act(() => hook.result.current.selectSuggestion(id, pick));
    expect(hook.result.current.status).toBe("loading");
    await flush(300);
    act(() => hook.result.current.setTravel(id, { mode: "drive", minutes: 25 }));
    await flush(300);
    expect(triangulate).not.toHaveBeenCalled();
    await flush(100);
    expect(triangulate).toHaveBeenCalledTimes(1);
    const sent = triangulate.mock.calls[0] as unknown as [{ minutes: number; label: string }[]];
    expect(sent[0]).toHaveLength(2);
    expect(sent[0][1]).toMatchObject({ minutes: 25, label: "Park Ave, NY" });
  });

  it("aborts the older call when an anchor changes", async () => {
    const { hook, triangulate } = setup();
    const signals: AbortSignal[] = [];
    triangulate.mockImplementation((async (_a: unknown, options?: { signal?: AbortSignal }) => {
      signals.push(options!.signal!);
      return new Promise(() => {});
    }) as never);
    act(() => hook.result.current.add());
    const id = hook.result.current.rows[1].id;
    act(() => hook.result.current.selectSuggestion(id, pick));
    await flush();
    expect(signals).toHaveLength(1);
    act(() => hook.result.current.setTravel(id, { mode: "walk", minutes: 10 }));
    expect(signals[0].aborted).toBe(true);
    await flush();
    expect(signals).toHaveLength(2);
  });

  it("returns at most five results at least 0.25 mi apart with reverse-geocoded labels", async () => {
    const { hook, reverseGeocode } = setup();
    act(() => hook.result.current.add());
    act(() => hook.result.current.selectSuggestion(hook.result.current.rows[1].id, pick));
    await flush();
    expect(hook.result.current.status).toBe("ready");
    const results = hook.result.current.data!.results;
    expect(results).toHaveLength(2);
    expect(results[0].score).toBe(80);
    expect(reverseGeocode).toHaveBeenCalledTimes(2);
    expect(results.map((r) => r.label)).toEqual(["12 Main St", "12 Main St"]);
    expect(hook.result.current.overlay.anchors).toHaveLength(2);
    expect(hook.result.current.overlay.anchors[0].geometry).toEqual(geometry);
    expect(hook.result.current.overlay.combined).toEqual(geometry);
    expect(hook.result.current.overlay.pins.map((p) => p.index)).toEqual([0, 1]);
  });

  it("falls back to coordinates text when reverse geocoding fails", async () => {
    const { hook, reverseGeocode } = setup();
    reverseGeocode.mockRejectedValue(new Error("no"));
    act(() => hook.result.current.add());
    act(() => hook.result.current.selectSuggestion(hook.result.current.rows[1].id, pick));
    await flush();
    expect(hook.result.current.data!.results.map((r) => r.label)).toEqual([
      "40.7100, -73.9900",
      "Some Street",
    ]);
  });

  it("is empty when the overlap is null, has no cells or no results", async () => {
    for (const response of [
      body({ combined: null }),
      body({ combined: iso(0) }),
      body({ results: [] }),
    ]) {
      const { hook, triangulate } = setup();
      triangulate.mockResolvedValue(response);
      act(() => hook.result.current.add());
      act(() => hook.result.current.selectSuggestion(hook.result.current.rows[1].id, pick));
      await flush();
      expect(hook.result.current.status).toBe("empty");
    }
  });

  it("notes estimates, reports errors and retries", async () => {
    const { hook, triangulate } = setup();
    triangulate.mockRejectedValueOnce(new Error("boom"));
    act(() => hook.result.current.add());
    act(() => hook.result.current.selectSuggestion(hook.result.current.rows[1].id, pick));
    await flush();
    expect(hook.result.current.status).toBe("error");
    triangulate.mockResolvedValueOnce(body({ isochrones: [iso(4, "estimate"), iso()] }));
    act(() => hook.result.current.retry());
    await flush();
    expect(hook.result.current.status).toBe("ready");
    expect(hook.result.current.data!.estimate).toBe(true);
  });

  it("goes idle again once the planner is removed", async () => {
    const { hook } = setup();
    act(() => hook.result.current.add());
    act(() => hook.result.current.selectSuggestion(hook.result.current.rows[1].id, pick));
    await flush();
    act(() => hook.result.current.remove(hook.result.current.rows[1].id));
    expect(hook.result.current.status).toBe("idle");
    expect(hook.result.current.data).toBeNull();
  });
});

describe("useTripPlanner URL", () => {
  it("hydrates rows from points and exposes them back", async () => {
    const { hook, reverseGeocode } = setup();
    act(() =>
      hook.result.current.hydrate([
        { lat: 40.7, lon: -74, mode: "transit", minutes: 20 },
        { lat: 40.8, lon: -73.9, mode: "drive", minutes: 15 },
      ]),
    );
    expect(hook.result.current.rows).toHaveLength(2);
    expect(hook.result.current.rows[0].label).toBe("40.7000, -74.0000");
    await act(async () => {
      await Promise.resolve();
    });
    expect(reverseGeocode).toHaveBeenCalledTimes(2);
    expect(hook.result.current.rows[0].label).toBe("12 Main St");
    expect(hook.result.current.urlPoints).toEqual([
      { lat: 40.7, lon: -74, mode: "transit", minutes: 20 },
      { lat: 40.8, lon: -73.9, mode: "drive", minutes: 15 },
    ]);
  });
});

describe("pickSpreadResults", () => {
  it("keeps the best five that are 0.25 mi apart", () => {
    const many = Array.from({ length: 10 }, (_, i) => ({ lat: 40 + i * 0.01, lon: -74, score: i }));
    const picked = pickSpreadResults(many);
    expect(picked).toHaveLength(5);
    expect(picked[0].score).toBe(9);
    expect(distanceMi(picked[0], picked[1])).toBeGreaterThanOrEqual(0.25);
  });
});
