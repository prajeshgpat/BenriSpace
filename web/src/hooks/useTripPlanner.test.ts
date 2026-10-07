import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ApiClient } from "@/lib/api/client";
import type { AreaGeometry, AreaScore, FactorKey, SubScores, Triangulation } from "@/lib/api/types";
import { FACTOR_KEY_LIST } from "@/lib/api/types";
import { makeAreaScore } from "@/test/fixtures";

import {
  NOT_FOUND_MESSAGE,
  TRIANGULATE_DEBOUNCE_MS,
  distanceMi,
  pickSpreadResults,
  useTripPlanner,
  type TripPlace,
  type TripPriorities,
  type TripTravel,
} from "./useTripPlanner";

const PLACE: TripPlace = { label: "Home", lat: 40.7, lon: -74 };
const SUBURB: TripPlace = { label: "Out", lat: 40.1, lon: -74.5 };
const TRAVEL: TripTravel = { mode: "transit", minutes: 20 };

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

function setup(place: TripPlace | null = PLACE, travel: TripTravel | null = TRAVEL) {
  const triangulate = vi.fn(async (): Promise<Triangulation> => body());
  const reverseGeocode = vi.fn(async () => ({ label: "12 Main St", latitude: 0, longitude: 0 }));
  const suggestAddresses = vi.fn(async () => [
    { label: "Park Ave, NY", latitude: 40.75, longitude: -73.97 },
  ]);
  const client = { triangulate, reverseGeocode, suggestAddresses } as never;
  const hook = renderHook(({ p, t }) => useTripPlanner(client, p, t), {
    initialProps: { p: place, t: travel },
  });
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
  it("adds up to two empty points of interest, then no more", () => {
    const { hook } = setup();
    expect(hook.result.current.canAdd).toBe(true);
    expect(hook.result.current.active).toBe(false);
    act(() => hook.result.current.add());
    const { rows } = hook.result.current;
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ label: "", error: null });
    expect(rows[0].lat).toBeUndefined();
    expect(hook.result.current.active).toBe(true);
    expect(hook.result.current.lastAddedId).toBe(rows[0].id);
    act(() => hook.result.current.add());
    expect(hook.result.current.rows).toHaveLength(2);
    expect(hook.result.current.canAdd).toBe(false);
    act(() => hook.result.current.add());
    expect(hook.result.current.rows).toHaveLength(2);
  });

  it("removing a point keeps the other, which becomes point 1; removing all is inactive", () => {
    const { hook } = setup();
    act(() => hook.result.current.add());
    act(() => hook.result.current.add());
    const [first, second] = hook.result.current.rows;
    act(() => hook.result.current.selectSuggestion(second.id, pick));
    act(() => hook.result.current.remove(first.id));
    expect(hook.result.current.rows.map((r) => r.id)).toEqual([second.id]);
    expect(hook.result.current.canAdd).toBe(true);
    expect(hook.result.current.overlay.pins.map((p) => p.index)).toEqual([0, 1]);
    act(() => hook.result.current.remove(second.id));
    expect(hook.result.current.rows).toEqual([]);
    expect(hook.result.current.active).toBe(false);
  });
});

describe("useTripPlanner address resolution", () => {
  it("resolves typed text through suggestAddresses with limit 1", async () => {
    const { hook, suggestAddresses } = setup();
    act(() => hook.result.current.add());
    const id = hook.result.current.rows[0].id;
    await act(async () => hook.result.current.submitText(id, "park ave"));
    expect(suggestAddresses).toHaveBeenCalledWith("park ave", { limit: 1 });
    expect(hook.result.current.rows[0]).toMatchObject({ label: "Park Ave, NY", lat: 40.75, error: null });
  });

  it("shows the not-found message when nothing matches", async () => {
    const { hook, suggestAddresses } = setup();
    suggestAddresses.mockResolvedValueOnce([]);
    act(() => hook.result.current.add());
    const id = hook.result.current.rows[0].id;
    await act(async () => hook.result.current.submitText(id, "zzzz"));
    expect(hook.result.current.rows[0].error).toBe(NOT_FOUND_MESSAGE);
    act(() => hook.result.current.selectSuggestion(id, pick));
    expect(hook.result.current.rows[0].error).toBeNull();
  });

  it("clearing a place drops its coordinates", () => {
    const { hook } = setup();
    act(() => hook.result.current.add());
    const id = hook.result.current.rows[0].id;
    act(() => hook.result.current.selectSuggestion(id, pick));
    act(() => hook.result.current.clearPlace(id));
    expect(hook.result.current.rows[0]).toMatchObject({ label: "", lat: undefined, lon: undefined });
  });

  it("fills a box from a tap on the map, then swaps in the address", async () => {
    const { hook, reverseGeocode } = setup();
    act(() => hook.result.current.add());
    const id = hook.result.current.rows[0].id;
    await act(async () => hook.result.current.setPlaceFromMap(id, { lat: 40.7411, lon: -73.9897 }));
    expect(reverseGeocode).toHaveBeenCalledWith({ lat: 40.7411, lon: -73.9897 });
    expect(hook.result.current.rows[0]).toMatchObject({
      label: "12 Main St",
      lat: 40.7411,
      lon: -73.9897,
      error: null,
    });
  });

  it("keeps the coordinates as the label when the tapped place has no address", async () => {
    const { hook, reverseGeocode } = setup();
    reverseGeocode.mockResolvedValue({ label: null, latitude: 0, longitude: 0 } as never);
    act(() => hook.result.current.add());
    const id = hook.result.current.rows[0].id;
    await act(async () => hook.result.current.setPlaceFromMap(id, { lat: 40.7411, lon: -73.9897 }));
    expect(hook.result.current.rows[0].lat).toBe(40.7411);
    expect(hook.result.current.rows[0].label).toContain("40.7411");
  });

  it("resolvePending looks up every box whose text was never confirmed", async () => {
    const { hook, suggestAddresses } = setup();
    suggestAddresses.mockImplementation((async (q: string) =>
      q === "nowhere" ? [] : [{ label: `Found ${q}`, latitude: 40.75, longitude: -73.97 }]) as never);
    act(() => hook.result.current.add());
    act(() => hook.result.current.add());
    const [first, second] = hook.result.current.rows;
    act(() => hook.result.current.setText(first.id, "park ave"));
    act(() => hook.result.current.setText(second.id, "nowhere"));
    await act(async () => {
      await hook.result.current.resolvePending();
    });
    expect(suggestAddresses).toHaveBeenCalledTimes(2);
    expect(hook.result.current.rows[0]).toMatchObject({ label: "Found park ave", lat: 40.75 });
    expect(hook.result.current.rows[1].error).toBe(NOT_FOUND_MESSAGE);
    // Only the one that failed is looked up again.
    await act(async () => {
      await hook.result.current.resolvePending();
    });
    expect(suggestAddresses).toHaveBeenCalledTimes(3);
  });

  it("resolvePending skips boxes that already match their place", async () => {
    const { hook, suggestAddresses } = setup();
    act(() => hook.result.current.add());
    const id = hook.result.current.rows[0].id;
    act(() => hook.result.current.selectSuggestion(id, pick));
    act(() => hook.result.current.setText(id, pick.label));
    await act(async () => {
      await hook.result.current.resolvePending();
    });
    expect(suggestAddresses).not.toHaveBeenCalled();
  });
});

describe("useTripPlanner triangulation", () => {
  it("does not call the API without a point of interest that has a place", async () => {
    const { hook, triangulate } = setup();
    act(() => hook.result.current.add());
    await flush(2000);
    expect(triangulate).not.toHaveBeenCalled();
    expect(hook.result.current.status).toBe("idle");
  });

  it("does not call the API without a searched place or travel time", async () => {
    const { hook, triangulate } = setup(null);
    act(() => hook.result.current.add());
    act(() => hook.result.current.selectSuggestion(hook.result.current.rows[0].id, pick));
    await flush(2000);
    expect(triangulate).not.toHaveBeenCalled();
    expect(hook.result.current.status).toBe("idle");
    hook.rerender({ p: PLACE, t: null });
    await flush(2000);
    expect(triangulate).not.toHaveBeenCalled();
  });

  it("sends the searched place first, then the points, all with the shared travel", async () => {
    const { hook, triangulate } = setup();
    act(() => hook.result.current.add());
    act(() => hook.result.current.add());
    const [first, second] = hook.result.current.rows;
    act(() => hook.result.current.selectSuggestion(first.id, pick));
    act(() => hook.result.current.selectSuggestion(second.id, { label: "Dock", latitude: 40.6, longitude: -74.02 }));
    await flush();
    expect(triangulate).toHaveBeenCalledTimes(1);
    const sent = (triangulate.mock.calls[0] as unknown as [unknown[]])[0];
    expect(sent).toEqual([
      { label: "Home", lat: 40.7, lon: -74, mode: "transit", minutes: 20 },
      { label: "Park Ave, NY", lat: 40.75, lon: -73.97, mode: "transit", minutes: 20 },
      { label: "Dock", lat: 40.6, lon: -74.02, mode: "transit", minutes: 20 },
    ]);
  });

  it("gives each point its own travel, falling back to the main one", async () => {
    const { hook, triangulate } = setup();
    act(() => hook.result.current.add());
    act(() => hook.result.current.add());
    const [first, second] = hook.result.current.rows;
    act(() => hook.result.current.selectSuggestion(first.id, pick));
    act(() => hook.result.current.selectSuggestion(second.id, { label: "Dock", latitude: 40.6, longitude: -74.02 }));
    act(() => hook.result.current.setTravel(second.id, "walk", 10));
    await flush();
    const sent = triangulate.mock.calls[0] as unknown as [{ mode: string; minutes: number }[]];
    // The searched place and the first point follow the main Travel time; the second is its own.
    expect(sent[0].map((a) => [a.mode, a.minutes])).toEqual([
      ["transit", 20],
      ["transit", 20],
      ["walk", 10],
    ]);

    // Changing the main travel moves the followers, not the point that was set apart.
    hook.rerender({ p: PLACE, t: { mode: "drive", minutes: 30 } });
    await flush();
    const again = triangulate.mock.calls.at(-1) as unknown as [{ mode: string; minutes: number }[]];
    expect(again[0].map((a) => [a.mode, a.minutes])).toEqual([
      ["drive", 30],
      ["drive", 30],
      ["walk", 10],
    ]);
  });

  it("never lets a point's own travel change the searched place's", async () => {
    const { hook, triangulate } = setup();
    act(() => hook.result.current.add());
    const [row] = hook.result.current.rows;
    act(() => hook.result.current.selectSuggestion(row.id, pick));
    act(() => hook.result.current.setTravel(row.id, "drive", 45));
    await flush();
    const sent = triangulate.mock.calls[0] as unknown as [{ mode: string; minutes: number }[]];
    expect(sent[0].map((a) => [a.mode, a.minutes])).toEqual([
      ["transit", 20],
      ["drive", 45],
    ]);
  });

  it("arms a new box, and disarms it when it is filled, removed or re-armed elsewhere", () => {
    const { hook } = setup();
    act(() => hook.result.current.add());
    const [first] = hook.result.current.rows;
    expect(hook.result.current.armedId).toBe(first.id);
    act(() => hook.result.current.arm(null));
    expect(hook.result.current.armedId).toBeNull();
    act(() => hook.result.current.arm(first.id));
    act(() => hook.result.current.setPlaceFromMap(first.id, { lat: 40.7, lon: -74 }));
    expect(hook.result.current.armedId).toBeNull();
    act(() => hook.result.current.arm(first.id));
    act(() => hook.result.current.remove(first.id));
    expect(hook.result.current.armedId).toBeNull();
  });

  it("reports whether any point has a place", () => {
    const { hook } = setup();
    act(() => hook.result.current.add());
    expect(hook.result.current.hasPlaces).toBe(false);
    act(() => hook.result.current.selectSuggestion(hook.result.current.rows[0].id, pick));
    expect(hook.result.current.hasPlaces).toBe(true);
  });

  it("waits 400 ms after the last change, then calls once", async () => {
    const { hook, triangulate } = setup();
    act(() => hook.result.current.add());
    act(() => hook.result.current.selectSuggestion(hook.result.current.rows[0].id, pick));
    expect(hook.result.current.status).toBe("loading");
    await flush(300);
    hook.rerender({ p: PLACE, t: { mode: "drive", minutes: 25 } });
    await flush(300);
    expect(triangulate).not.toHaveBeenCalled();
    await flush(100);
    expect(triangulate).toHaveBeenCalledTimes(1);
    const sent = triangulate.mock.calls[0] as unknown as [{ minutes: number; mode: string }[]];
    expect(sent[0]).toHaveLength(2);
    expect(sent[0].map((a) => [a.mode, a.minutes])).toEqual([
      ["drive", 25],
      ["drive", 25],
    ]);
  });

  it("aborts the older call and runs again when the travel time or the place changes", async () => {
    const { hook, triangulate } = setup();
    const signals: AbortSignal[] = [];
    triangulate.mockImplementation((async (_a: unknown, options?: { signal?: AbortSignal }) => {
      signals.push(options!.signal!);
      return new Promise(() => {});
    }) as never);
    act(() => hook.result.current.add());
    act(() => hook.result.current.selectSuggestion(hook.result.current.rows[0].id, pick));
    await flush();
    expect(signals).toHaveLength(1);
    hook.rerender({ p: PLACE, t: { mode: "walk", minutes: 10 } });
    expect(signals[0].aborted).toBe(true);
    await flush();
    expect(signals).toHaveLength(2);
    hook.rerender({ p: SUBURB, t: { mode: "walk", minutes: 10 } });
    expect(signals[1].aborted).toBe(true);
    await flush();
    expect(signals).toHaveLength(3);
  });

  it("returns at most five results at least 0.25 mi apart with reverse-geocoded labels", async () => {
    const { hook, reverseGeocode } = setup();
    act(() => hook.result.current.add());
    act(() => hook.result.current.selectSuggestion(hook.result.current.rows[0].id, pick));
    await flush();
    expect(hook.result.current.status).toBe("ready");
    const results = hook.result.current.data!.results;
    expect(results).toHaveLength(2);
    expect(results[0].score).toBe(80);
    expect(reverseGeocode).toHaveBeenCalledTimes(2);
    expect(results.map((r) => r.label)).toEqual(["12 Main St", "12 Main St"]);
    expect(hook.result.current.overlay.anchors).toHaveLength(2);
    expect(hook.result.current.overlay.anchors[0]).toMatchObject({ index: 0, label: "Home" });
    expect(hook.result.current.overlay.anchors[0].geometry).toEqual(geometry);
    expect(hook.result.current.overlay.combined).toEqual(geometry);
    expect(hook.result.current.overlay.pins.map((p) => p.index)).toEqual([0, 1]);
  });

  it("falls back to coordinates text when reverse geocoding fails", async () => {
    const { hook, reverseGeocode } = setup();
    reverseGeocode.mockRejectedValue(new Error("no"));
    act(() => hook.result.current.add());
    act(() => hook.result.current.selectSuggestion(hook.result.current.rows[0].id, pick));
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
      act(() => hook.result.current.selectSuggestion(hook.result.current.rows[0].id, pick));
      await flush();
      expect(hook.result.current.status).toBe("empty");
    }
  });

  it("notes estimates, reports errors and retries", async () => {
    const { hook, triangulate } = setup();
    triangulate.mockRejectedValueOnce(new Error("boom"));
    act(() => hook.result.current.add());
    act(() => hook.result.current.selectSuggestion(hook.result.current.rows[0].id, pick));
    await flush();
    expect(hook.result.current.status).toBe("error");
    triangulate.mockResolvedValueOnce(body({ isochrones: [iso(4, "estimate"), iso()] }));
    act(() => hook.result.current.retry());
    await flush();
    expect(hook.result.current.status).toBe("ready");
    expect(hook.result.current.data!.estimate).toBe(true);
  });

  it("goes idle again once the point is removed", async () => {
    const { hook } = setup();
    act(() => hook.result.current.add());
    act(() => hook.result.current.selectSuggestion(hook.result.current.rows[0].id, pick));
    await flush();
    act(() => hook.result.current.remove(hook.result.current.rows[0].id));
    expect(hook.result.current.status).toBe("idle");
    expect(hook.result.current.data).toBeNull();
  });
});

describe("useTripPlanner URL", () => {
  it("hydrates points of interest and exposes them back", async () => {
    const { hook, reverseGeocode } = setup();
    act(() =>
      hook.result.current.hydrate([
        { lat: 40.7, lon: -74 },
        { lat: 40.8, lon: -73.9 },
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
      { lat: 40.7, lon: -74 },
      { lat: 40.8, lon: -73.9 },
    ]);
  });

  it("hydrates a single point", () => {
    const { hook } = setup();
    act(() => hook.result.current.hydrate([{ lat: 40.7, lon: -74 }]));
    expect(hook.result.current.rows).toHaveLength(1);
    expect(hook.result.current.canAdd).toBe(true);
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


describe("useTripPlanner selected-factor scores", () => {
  const noScores = Object.fromEntries(FACTOR_KEY_LIST.map((k) => [k, null])) as unknown as SubScores;
  // Main St is great at groceries and poor at transit; Side St is the reverse.
  const bySpot: Record<string, Partial<SubScores>> = {
    "40.71": { grocery: 90, transit: 10 },
    "40.8": { grocery: 20, transit: 80 },
  };
  const area = (lat: number): AreaScore => {
    const base = makeAreaScore();
    return {
      ...base,
      score: { ...base.score, subScores: { ...noScores, ...bySpot[String(lat)] } },
    };
  };

  function setupPriorities(initial: TripPriorities | undefined) {
    const triangulate = vi.fn<ApiClient["triangulate"]>(async () => body());
    const getAreaByCoordinates = vi.fn(async ({ lat }: { lat: number; lon: number }) => area(lat));
    const client = {
      triangulate,
      getAreaByCoordinates,
      reverseGeocode: vi.fn(async () => ({ label: null, latitude: 0, longitude: 0 })),
      suggestAddresses: vi.fn(async () => []),
    } as never;
    const hook = renderHook(({ pr }) => useTripPlanner(client, PLACE, TRAVEL, pr), {
      initialProps: { pr: initial },
    });
    act(() => hook.result.current.add());
    act(() => hook.result.current.selectSuggestion(hook.result.current.rows[0].id, pick));
    return { hook, triangulate, getAreaByCoordinates };
  }

  it("sends the selected factors and importance, and none when all are selected", async () => {
    const { hook, triangulate } = setupPriorities({
      factors: ["grocery", "transit"],
      weights: { grocery: 3 },
    });
    await flush();
    expect(triangulate).toHaveBeenCalledTimes(1);
    expect(triangulate.mock.calls[0][1]).toMatchObject({
      factors: ["grocery", "transit"],
      weights: { grocery: 3 },
    });
    hook.rerender({ pr: { factors: [...FACTOR_KEY_LIST] } });
    await flush();
    expect(triangulate).toHaveBeenCalledTimes(2);
    expect(triangulate.mock.calls[1][1]?.factors).toBeUndefined();
  });

  it("scores each area as the score card does, then orders by that score", async () => {
    const { hook, getAreaByCoordinates } = setupPriorities({
      factors: ["grocery", "transit"] as FactorKey[],
      weights: { grocery: 1, transit: 1 },
    });
    await flush();
    expect(getAreaByCoordinates).toHaveBeenCalledTimes(2);
    // Equal weights: Main St (90+10)/2 = 50, Side St (20+80)/2 = 50; use transit-only below.
    expect(hook.result.current.data!.results.map((r) => r.score)).toEqual([50, 50]);
    hook.rerender({ pr: { factors: ["transit"] } });
    await flush();
    const results = hook.result.current.data!.results;
    expect(results.map((r) => [r.lat, r.score])).toEqual([
      [40.8, 80],
      [40.71, 10],
    ]);
  });

  it("keeps loading until the area scores arrive, and re-requests when the selection changes", async () => {
    const { hook, triangulate } = setupPriorities({ factors: ["grocery"] });
    await flush();
    expect(hook.result.current.status).toBe("ready");
    expect(hook.result.current.data!.results[0]).toMatchObject({ lat: 40.71, score: 90 });
    hook.rerender({ pr: { factors: ["transit"] } });
    expect(hook.result.current.status).toBe("loading");
    await flush();
    expect(triangulate).toHaveBeenCalledTimes(2);
    expect(hook.result.current.data!.results[0]).toMatchObject({ lat: 40.8, score: 80 });
  });

  it("falls back to the API score for an area that can't be looked up", async () => {
    const triangulate = vi.fn(async (): Promise<Triangulation> => body());
    const client = {
      triangulate,
      getAreaByCoordinates: vi.fn(async () => {
        throw new Error("down");
      }),
      reverseGeocode: vi.fn(async () => ({ label: null, latitude: 0, longitude: 0 })),
      suggestAddresses: vi.fn(async () => []),
    } as never;
    const hook = renderHook(() => useTripPlanner(client, PLACE, TRAVEL, { factors: ["grocery"] }));
    act(() => hook.result.current.add());
    act(() => hook.result.current.selectSuggestion(hook.result.current.rows[0].id, pick));
    await flush();
    expect(hook.result.current.data!.results.map((r) => r.score)).toEqual([80, 70]);
  });
});
