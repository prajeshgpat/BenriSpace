import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Similar } from "@/lib/api/types";

import { useImprove } from "./useImprove";
import { useSimilar } from "./useSimilar";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const similar = (label: string): Similar => ({
  minSeparationMi: 1,
  priorities: [],
  results: [
    {
      latitude: 1,
      longitude: 2,
      direction: "N",
      distanceLabel: "2 mi",
      similarity: 90,
      compositeScore: 70,
      areaLabel: label,
      differences: [],
      summary: "",
    },
  ],
});

const POINT = { lat: 40.7, lon: -74 };
const flush = () => act(async () => {});

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("useSimilar", () => {
  it("is idle without a point and requests nothing", () => {
    const client = { getSimilar: vi.fn() };
    const { result } = renderHook(() => useSimilar(null, client));
    expect(result.current.status).toBe("idle");
    expect(client.getSimilar).not.toHaveBeenCalled();
  });

  it("fetches at once for a new point, passing the selection", async () => {
    const client = { getSimilar: vi.fn(async () => similar("A")) };
    const { result } = renderHook(() =>
      useSimilar(POINT, client, { factors: ["transit"], weights: { transit: 2 } }),
    );
    await flush();

    expect(client.getSimilar).toHaveBeenCalledWith(
      40.7,
      -74,
      expect.objectContaining({ factors: ["transit"], weights: { transit: 2 } }),
    );
    expect(result.current.status).toBe("ready");
    expect(result.current.updating).toBe(false);
  });

  it("debounces selection changes into one request and keeps the old list marked updating", async () => {
    const second = deferred<Similar>();
    const getSimilar = vi
      .fn<(lat: number, lon: number, q: unknown) => Promise<Similar>>()
      .mockResolvedValueOnce(similar("old"))
      .mockReturnValueOnce(second.promise);
    const client = { getSimilar };
    const { result, rerender } = renderHook(
      ({ factors }: { factors?: ("transit" | "cafe" | "grocery")[] }) =>
        useSimilar(POINT, client, { factors }),
      { initialProps: { factors: undefined as ("transit" | "cafe" | "grocery")[] | undefined } },
    );
    await flush();
    expect(getSimilar).toHaveBeenCalledTimes(1);

    rerender({ factors: ["transit"] });
    act(() => vi.advanceTimersByTime(200));
    rerender({ factors: ["transit", "cafe"] });
    act(() => vi.advanceTimersByTime(399));
    await flush();
    expect(getSimilar).toHaveBeenCalledTimes(1);
    expect(result.current.updating).toBe(true);
    expect(result.current.data?.results[0].areaLabel).toBe("old");

    act(() => vi.advanceTimersByTime(1));
    await flush();
    expect(getSimilar).toHaveBeenCalledTimes(2);
    expect(getSimilar.mock.calls[1][2]).toMatchObject({ factors: ["transit", "cafe"] });
    expect(result.current.data?.results[0].areaLabel).toBe("old");
    expect(result.current.updating).toBe(true);

    await act(async () => second.resolve(similar("new")));
    expect(result.current.data?.results[0].areaLabel).toBe("new");
    expect(result.current.updating).toBe(false);
  });

  it("aborts the superseded request so a stale response is never shown", async () => {
    const first = deferred<Similar>();
    const signals: AbortSignal[] = [];
    const getSimilar = vi.fn(
      (_lat: number, _lon: number, q: { signal: AbortSignal }) => {
        signals.push(q.signal);
        return signals.length === 1 ? first.promise : Promise.resolve(similar("new"));
      },
    );
    const { result, rerender } = renderHook(
      ({ factors }: { factors?: "cafe"[] }) => useSimilar(POINT, { getSimilar }, { factors }),
      { initialProps: { factors: undefined as "cafe"[] | undefined } },
    );
    rerender({ factors: ["cafe"] });
    act(() => vi.advanceTimersByTime(400));
    await flush();
    expect(signals[0].aborted).toBe(true);

    await act(async () => first.resolve(similar("stale")));
    expect(result.current.data?.results[0].areaLabel).toBe("new");
  });

  it("does not show another point's result while the new point loads", async () => {
    const next = deferred<Similar>();
    const getSimilar = vi
      .fn<(lat: number, lon: number, q: unknown) => Promise<Similar>>()
      .mockResolvedValueOnce(similar("here"))
      .mockReturnValueOnce(next.promise);
    const { result, rerender } = renderHook(
      ({ point }) => useSimilar(point, { getSimilar }),
      { initialProps: { point: POINT } },
    );
    await flush();
    rerender({ point: { lat: 41, lon: -73 } });
    expect(result.current).toMatchObject({ status: "loading", data: null });
  });

  it("is unavailable on failure and idle when no factors are selected", async () => {
    const failing = { getSimilar: vi.fn(async () => Promise.reject(new Error("x"))) };
    const { result } = renderHook(() => useSimilar(POINT, failing));
    await flush();
    expect(result.current.status).toBe("unavailable");

    const client = { getSimilar: vi.fn() };
    const none = renderHook(() => useSimilar(POINT, client, { factors: [] }));
    expect(none.result.current.status).toBe("idle");
    expect(client.getSimilar).not.toHaveBeenCalled();
  });
});

describe("useImprove selection", () => {
  it("refetches once, debounced, when the selection changes", async () => {
    const body = { composite: 1, radiusMi: 1, suggestions: [], bestNearby: null, priorities: [] };
    const getImprove = vi.fn(async () => body);
    const { rerender } = renderHook(
      ({ factors }: { factors?: "cafe"[] }) => useImprove(POINT, { getImprove }, { factors }),
      { initialProps: { factors: undefined as "cafe"[] | undefined } },
    );
    await flush();
    rerender({ factors: ["cafe"] });
    act(() => vi.advanceTimersByTime(399));
    expect(getImprove).toHaveBeenCalledTimes(1);
    act(() => vi.advanceTimersByTime(1));
    await flush();
    expect(getImprove).toHaveBeenCalledTimes(2);
    expect(getImprove).toHaveBeenLastCalledWith(
      40.7,
      -74,
      expect.objectContaining({ factors: ["cafe"] }),
    );
  });
});
