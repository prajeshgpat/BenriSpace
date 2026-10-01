import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ApiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { Explanation, Score } from "@/lib/api/types";
import { makeExplanation, makeScore } from "@/test/fixtures";

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

function makeClient(overrides: Partial<ApiClient> = {}): ApiClient {
  return {
    getScore: vi.fn(async () => makeScore()),
    getScoreExplanation: vi.fn(async () => makeExplanation()),
    ...overrides,
  };
}

describe("useScoreLookup", () => {
  it("stays idle and makes no request without an address", () => {
    const client = makeClient();

    const { result } = renderHook(() => useScoreLookup(null, client));

    expect(result.current.state).toEqual({ status: "idle" });
    expect(client.getScore).not.toHaveBeenCalled();
  });

  it("loads the score first, then fills in the explanation", async () => {
    const explanation = deferred<Explanation>();
    const client = makeClient({
      getScoreExplanation: vi.fn(() => explanation.promise),
    });

    const { result } = renderHook(() => useScoreLookup("350 5th Ave", client));

    expect(result.current.state).toEqual({ status: "loading", address: "350 5th Ave" });

    await waitFor(() => expect(result.current.state.status).toBe("success"));
    expect(result.current.state).toMatchObject({
      address: "350 5th Ave",
      explanation: { status: "loading" },
    });
    expect(client.getScoreExplanation).toHaveBeenCalledWith(
      makeScore().geoEntityId,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );

    await act(async () => explanation.resolve(makeExplanation({ explanation: "Because." })));

    expect(result.current.state).toMatchObject({
      status: "success",
      explanation: { status: "ready", text: "Because." },
    });
  });

  it("surfaces a score failure as an error state and skips the explanation", async () => {
    const error = new ApiError("not-found", "Outside coverage", { status: 404 });
    const client = makeClient({ getScore: vi.fn(async () => Promise.reject(error)) });

    const { result } = renderHook(() => useScoreLookup("Washington DC", client));

    await waitFor(() => expect(result.current.state.status).toBe("error"));
    expect(result.current.state).toEqual({
      status: "error",
      address: "Washington DC",
      error,
    });
    expect(client.getScoreExplanation).not.toHaveBeenCalled();
  });

  it("wraps an unexpected throw in an ApiError", async () => {
    const client = makeClient({
      getScore: vi.fn(async () => Promise.reject(new RangeError("boom"))),
    });

    const { result } = renderHook(() => useScoreLookup("anywhere", client));

    await waitFor(() => expect(result.current.state.status).toBe("error"));
    expect(result.current.state).toMatchObject({ error: { kind: "server" } });
  });

  it.each([
    ["the request fails", () => Promise.reject(new ApiError("network", "down"))],
    ["the text is blank", () => Promise.resolve(makeExplanation({ explanation: "  " }))],
  ])("keeps the score when the explanation is unavailable because %s", async (_label, respond) => {
    const client = makeClient({ getScoreExplanation: vi.fn(respond) });

    const { result } = renderHook(() => useScoreLookup("350 5th Ave", client));

    await waitFor(() =>
      expect(result.current.state).toMatchObject({
        status: "success",
        explanation: { status: "unavailable" },
      }),
    );
  });

  it("ignores a slow response for an address the user has moved on from", async () => {
    const first = deferred<Score>();
    const getScore = vi.fn<ApiClient["getScore"]>((address) =>
      address === "first" ? first.promise : Promise.resolve(makeScore({ compositeScore: 88 })),
    );
    const client = makeClient({ getScore });

    const { result, rerender } = renderHook(
      ({ address }) => useScoreLookup(address, client),
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

    const { result } = renderHook(() => useScoreLookup("350 5th Ave", client));
    await waitFor(() => expect(result.current.state.status).toBe("error"));

    act(() => result.current.retry());
    expect(result.current.state.status).toBe("loading");

    await waitFor(() => expect(result.current.state.status).toBe("success"));
    expect(getScore).toHaveBeenCalledTimes(2);
  });

  it("returns to idle when the address is cleared", async () => {
    const client = makeClient();
    const { result, rerender } = renderHook(
      ({ address }: { address: string | null }) => useScoreLookup(address, client),
      { initialProps: { address: "350 5th Ave" as string | null } },
    );
    await waitFor(() => expect(result.current.state.status).toBe("success"));

    rerender({ address: null });

    expect(result.current.state).toEqual({ status: "idle" });
  });
});
