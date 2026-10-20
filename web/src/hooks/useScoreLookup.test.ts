import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ScoreTarget } from "@/lib/address";
import type { ApiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { Score } from "@/lib/api/types";
import { makeAreaScore, makeScore, stubClient } from "@/test/fixtures";

import { useScoreLookup } from "./useScoreLookup";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const byAddress = (address: string): ScoreTarget => ({ kind: "address", address });

function makeClient(overrides: Partial<ApiClient> = {}): ApiClient {
  return stubClient({
    getScore: vi.fn(async () => makeScore()),
    getScoreByCoordinates: vi.fn(async () => makeScore()),
    ...overrides,
  });
}

describe("useScoreLookup", () => {
  it("stays idle and makes no request without an address", () => {
    const client = makeClient();

    const { result } = renderHook(() => useScoreLookup(null, client));

    expect(result.current.state).toEqual({ status: "idle" });
    expect(client.getScore).not.toHaveBeenCalled();
  });

  it("loads the score for an address", async () => {
    const client = makeClient();

    const { result } = renderHook(() => useScoreLookup(byAddress("350 5th Ave"), client));

    expect(result.current.state).toEqual({ status: "loading", address: "350 5th Ave" });
    await waitFor(() => expect(result.current.state.status).toBe("success"));
    expect(result.current.state).toMatchObject({ address: "350 5th Ave", score: makeScore() });
    expect(client.getScore).toHaveBeenCalledWith(
      "350 5th Ave",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it("surfaces a score failure as an error state", async () => {
    const error = new ApiError("not-found", "Outside coverage", { status: 404 });
    const client = makeClient({ getScore: vi.fn(async () => Promise.reject(error)) });

    const { result } = renderHook(() => useScoreLookup(byAddress("Washington DC"), client));

    await waitFor(() => expect(result.current.state.status).toBe("error"));
    expect(result.current.state).toEqual({
      status: "error",
      address: "Washington DC",
      error,
    });
  });

  it("wraps an unexpected throw in an ApiError", async () => {
    const client = makeClient({
      getScore: vi.fn(async () => Promise.reject(new RangeError("boom"))),
    });

    const { result } = renderHook(() => useScoreLookup(byAddress("anywhere"), client));

    await waitFor(() => expect(result.current.state.status).toBe("error"));
    expect(result.current.state).toMatchObject({ error: { kind: "server" } });
  });

  it("ignores a slow response for an address the user has moved on from", async () => {
    const first = deferred<Score>();
    const getScore = vi.fn<ApiClient["getScore"]>((address) =>
      address === "first" ? first.promise : Promise.resolve(makeScore({ compositeScore: 88 })),
    );
    const client = makeClient({ getScore });

    const { result, rerender } = renderHook(
      ({ address }) => useScoreLookup(address === null ? null : byAddress(address), client),
      { initialProps: { address: "first" } },
    );
    const firstSignal = getScore.mock.calls[0][1]?.signal;

    rerender({ address: "second" });
    expect(result.current.state).toEqual({ status: "loading", address: "second" });
    expect(firstSignal?.aborted).toBe(true);

    await waitFor(() => expect(result.current.state.status).toBe("success"));
    await act(async () => first.resolve(makeScore({ compositeScore: 12 })));

    expect(result.current.state).toMatchObject({
      address: "second",
      score: { compositeScore: 88 },
    });
  });

  it("re-runs the lookup on retry", async () => {
    const getScore = vi
      .fn<ApiClient["getScore"]>()
      .mockRejectedValueOnce(new ApiError("network", "down"))
      .mockResolvedValueOnce(makeScore());
    const client = makeClient({ getScore });

    const { result } = renderHook(() => useScoreLookup(byAddress("350 5th Ave"), client));
    await waitFor(() => expect(result.current.state.status).toBe("error"));

    act(() => result.current.retry());
    expect(result.current.state.status).toBe("loading");

    await waitFor(() => expect(result.current.state.status).toBe("success"));
    expect(getScore).toHaveBeenCalledTimes(2);
  });

  it("returns to idle when the address is cleared", async () => {
    const client = makeClient();
    const { result, rerender } = renderHook(
      ({ address }: { address: string | null }) => useScoreLookup(address === null ? null : byAddress(address), client),
      { initialProps: { address: "350 5th Ave" as string | null } },
    );
    await waitFor(() => expect(result.current.state.status).toBe("success"));

    rerender({ address: null });

    expect(result.current.state).toEqual({ status: "idle" });
  });

  it("looks coordinates up directly, labelled for display", async () => {
    const client = makeClient();
    const target: ScoreTarget = {
      kind: "coordinates",
      lat: 40.7484,
      lon: -73.9857,
      label: "Empire State Building",
    };

    const { result } = renderHook(() => useScoreLookup(target, client));

    expect(result.current.state).toEqual({
      status: "loading",
      address: "Empire State Building",
    });
    await waitFor(() => expect(result.current.state.status).toBe("success"));
    expect(client.getScoreByCoordinates).toHaveBeenCalledWith(
      { lat: 40.7484, lon: -73.9857 },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(client.getScore).not.toHaveBeenCalled();
  });

  describe("area lookups for coordinates", () => {
    const click: ScoreTarget = { kind: "coordinates", lat: 40.725, lon: -73.995, label: "40.7250, -73.9950" };

    it("uses the area and makes no further calls", async () => {
      const area = makeAreaScore();
      const client = makeClient({ getAreaByCoordinates: vi.fn(async () => area) });

      const { result } = renderHook(() => useScoreLookup(click, client));

      await waitFor(() => expect(result.current.state.status).toBe("success"));
      expect(result.current.state).toMatchObject({
        address: "40.7250, -73.9950",
        score: area.score,
        area: area.area,
      });
      expect(client.getAreaByCoordinates).toHaveBeenCalledWith(
        { lat: 40.725, lon: -73.995 },
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      );
      expect(client.getScoreByCoordinates).not.toHaveBeenCalled();
    });

    it.each([
      ["404", new ApiError("not-found", "none", { status: 404 })],
      ["500", new ApiError("server", "boom", { status: 500 })],
      ["a network failure", new ApiError("network", "down")],
      ["an invalid body", new ApiError("invalid-response", "bad")],
    ])("falls back to the grid square on %s, without an error", async (_label, error) => {
      const client = makeClient({ getAreaByCoordinates: vi.fn(async () => Promise.reject(error)) });

      const { result } = renderHook(() => useScoreLookup(click, client));

      await waitFor(() => expect(result.current.state.status).toBe("success"));
      expect(result.current.state).toMatchObject({ area: null });
      expect(client.getScoreByCoordinates).toHaveBeenCalledTimes(1);
    });

    it("still reports an error when the fallback fails too", async () => {
      const client = makeClient({
        getAreaByCoordinates: vi.fn(async () => Promise.reject(new ApiError("server", "x"))),
        getScoreByCoordinates: vi.fn(async () =>
          Promise.reject(new ApiError("not-found", "outside", { status: 404 })),
        ),
      });
      const { result } = renderHook(() => useScoreLookup(click, client));
      await waitFor(() => expect(result.current.state.status).toBe("error"));
      expect(result.current.state).toMatchObject({ error: { kind: "not-found" } });
    });

    it("resolves the area for a best-areas pick like a map click", async () => {
      const client = makeClient({ getAreaByCoordinates: vi.fn(async () => makeAreaScore()) });
      const { result } = renderHook(() => useScoreLookup(click, client));
      await waitFor(() => expect(result.current.state.status).toBe("success"));
      expect(client.getAreaByCoordinates).toHaveBeenCalledTimes(1);
      expect(result.current.state).not.toMatchObject({ area: null });
    });

    it("never asks for an area for a typed address", async () => {
      const client = makeClient({ getAreaByCoordinates: vi.fn(async () => makeAreaScore()) });
      const { result } = renderHook(() => useScoreLookup(byAddress("350 5th Ave"), client));
      await waitFor(() => expect(result.current.state.status).toBe("success"));
      expect(client.getAreaByCoordinates).not.toHaveBeenCalled();
    });
  });
});
