import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ScoreTarget } from "@/lib/address";
import type { ApiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { AreaExplanation, Explanation, Score } from "@/lib/api/types";
import { makeAreaScore, makeExplanation, makeScore, stubClient } from "@/test/fixtures";

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
    getScoreExplanation: vi.fn(async () => makeExplanation()),
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

  it("loads the score first, then fills in the explanation", async () => {
    const explanation = deferred<Explanation>();
    const client = makeClient({
      getScoreExplanation: vi.fn(() => explanation.promise),
    });

    const { result } = renderHook(() => useScoreLookup(byAddress("350 5th Ave"), client));

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

    const { result } = renderHook(() => useScoreLookup(byAddress("Washington DC"), client));

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

    const { result } = renderHook(() => useScoreLookup(byAddress("anywhere"), client));

    await waitFor(() => expect(result.current.state.status).toBe("error"));
    expect(result.current.state).toMatchObject({ error: { kind: "server" } });
  });

  it.each([
    ["the request fails", () => Promise.reject(new ApiError("network", "down"))],
    ["the text is blank", () => Promise.resolve(makeExplanation({ explanation: "  " }))],
  ])("keeps the score when the explanation is unavailable because %s", async (_label, respond) => {
    const client = makeClient({ getScoreExplanation: vi.fn(respond) });

    const { result } = renderHook(() => useScoreLookup(byAddress("350 5th Ave"), client));

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

    it("uses the area, its inline explanation, and makes no further calls", async () => {
      const area = makeAreaScore();
      const client = makeClient({ getAreaByCoordinates: vi.fn(async () => area) });

      const { result } = renderHook(() => useScoreLookup(click, client));

      await waitFor(() => expect(result.current.state.status).toBe("success"));
      expect(result.current.state).toMatchObject({
        address: "40.7250, -73.9950",
        score: area.score,
        area: area.area,
        explanation: { status: "ready", text: area.explanation },
      });
      expect(client.getAreaByCoordinates).toHaveBeenCalledWith(
        { lat: 40.725, lon: -73.995 },
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      );
      expect(client.getScoreByCoordinates).not.toHaveBeenCalled();
      expect(client.getScoreExplanation).not.toHaveBeenCalled();
    });

    describe("AI explanation upgrade", () => {
      const aiBody = { explanation: "AI text.", source: "ai", areaId: 7, priorities: [] as never[] } as const;

      it("shows the rules text at once, then swaps in the AI text", async () => {
        const ai = deferred<AreaExplanation>();
        const area = makeAreaScore();
        const client = makeClient({
          getAreaByCoordinates: vi.fn(async () => area),
          getAreaExplanation: vi.fn(() => ai.promise),
        });
        const { result } = renderHook(() => useScoreLookup(click, client));

        await waitFor(() =>
          expect(result.current.state).toMatchObject({
            explanation: { status: "ready", text: area.explanation, explanationSource: "rules" },
          }),
        );
        expect(client.getAreaExplanation).toHaveBeenCalledWith(
          40.725,
          -73.995,
          expect.objectContaining({ signal: expect.any(AbortSignal) }),
        );

        await act(async () => ai.resolve(aiBody));
        expect(result.current.state).toMatchObject({
          score: area.score,
          explanation: { status: "ready", text: "AI text.", explanationSource: "ai" },
        });
      });

      it.each([
        ["fails", () => Promise.reject(new ApiError("server", "x"))],
        ["answers with rules", () => Promise.resolve({ ...aiBody, source: "rules" as const })],
      ])("keeps the rules text silently when the request %s", async (_l, respond) => {
        const area = makeAreaScore();
        const getAreaExplanation = vi.fn(respond);
        const client = makeClient({
          getAreaByCoordinates: vi.fn(async () => area),
          getAreaExplanation,
        });
        const { result } = renderHook(() => useScoreLookup(click, client));
        await waitFor(() => expect(getAreaExplanation).toHaveBeenCalled());
        await act(async () => {});
        expect(result.current.state).toMatchObject({
          status: "success",
          explanation: { status: "ready", text: area.explanation, explanationSource: "rules" },
        });
      });

      it("ignores an AI response that arrives after the target changed", async () => {
        const ai = deferred<AreaExplanation>();
        const other: ScoreTarget = { ...click, lat: 40.8, lon: -73.9, label: "other" };
        const second = makeAreaScore({ explanation: "Second rules." });
        const getAreaByCoordinates = vi
          .fn()
          .mockResolvedValueOnce(makeAreaScore())
          .mockResolvedValueOnce(second);
        const getAreaExplanation = vi
          .fn()
          .mockImplementationOnce(() => ai.promise)
          .mockImplementationOnce(() => new Promise(() => {}));
        const client = makeClient({ getAreaByCoordinates, getAreaExplanation });
        const { result, rerender } = renderHook(({ t }) => useScoreLookup(t, client), {
          initialProps: { t: click },
        });
        await waitFor(() => expect(getAreaExplanation).toHaveBeenCalledTimes(1));

        rerender({ t: other });
        await waitFor(() => expect(getAreaExplanation).toHaveBeenCalledTimes(2));
        await act(async () => ai.resolve(aiBody));

        expect(result.current.state).toMatchObject({
          explanation: { text: "Second rules.", explanationSource: "rules" },
        });
      });
    });

    it("uses the source reported by the cell explanation", async () => {
      const client = makeClient({
        getAreaByCoordinates: vi.fn(async () => Promise.reject(new ApiError("not-found", "n"))),
        getScoreExplanation: vi.fn(async () => makeExplanation({ source: "ai" })),
      });
      const { result } = renderHook(() => useScoreLookup(click, client));
      await waitFor(() =>
        expect(result.current.state).toMatchObject({
          explanation: { status: "ready", explanationSource: "ai" },
        }),
      );
    });

    it("marks a blank inline explanation unavailable", async () => {
      const client = makeClient({
        getAreaByCoordinates: vi.fn(async () => makeAreaScore({ explanation: " " })),
      });
      const { result } = renderHook(() => useScoreLookup(click, client));
      await waitFor(() =>
        expect(result.current.state).toMatchObject({ explanation: { status: "unavailable" } }),
      );
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
      await waitFor(() =>
        expect(result.current.state).toMatchObject({ explanation: { status: "ready" } }),
      );
      expect(client.getScoreExplanation).toHaveBeenCalledTimes(1);
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

    it("stays cell-based for a best-areas pick", async () => {
      const client = makeClient({ getAreaByCoordinates: vi.fn(async () => makeAreaScore()) });
      const pick: ScoreTarget = { ...click, precision: "cell" };

      const { result } = renderHook(() => useScoreLookup(pick, client));

      await waitFor(() => expect(result.current.state.status).toBe("success"));
      expect(client.getAreaByCoordinates).not.toHaveBeenCalled();
      expect(client.getScoreByCoordinates).toHaveBeenCalledTimes(1);
      expect(result.current.state).toMatchObject({ area: null });
    });

    it("never asks for an area for a typed address", async () => {
      const client = makeClient({ getAreaByCoordinates: vi.fn(async () => makeAreaScore()) });
      const { result } = renderHook(() => useScoreLookup(byAddress("350 5th Ave"), client));
      await waitFor(() => expect(result.current.state.status).toBe("success"));
      expect(client.getAreaByCoordinates).not.toHaveBeenCalled();
    });
  });
});

describe("useScoreLookup: explanation follows the selected factors", () => {
  const click: ScoreTarget = { kind: "coordinates", lat: 40.725, lon: -73.995, label: "x" };
  const ai = (text: string): AreaExplanation => ({
    explanation: text,
    source: "ai",
    areaId: 7,
    priorities: [],
  });

  it("re-requests only the explanation, debounced, keeping the old text marked updating", async () => {
    vi.useFakeTimers();
    try {
      const next = deferred<AreaExplanation>();
      const getAreaExplanation = vi
        .fn<ApiClient["getAreaExplanation"]>()
        .mockResolvedValueOnce(ai("All factors text."))
        .mockReturnValueOnce(next.promise);
      const client = makeClient({
        getAreaByCoordinates: vi.fn(async () => makeAreaScore()),
        getAreaExplanation,
      });
      const { result, rerender } = renderHook(
        ({ factors }: { factors?: ("transit" | "cafe")[] }) =>
          useScoreLookup(click, client, { factors }),
        { initialProps: { factors: undefined as ("transit" | "cafe")[] | undefined } },
      );
      await act(async () => {});
      expect(result.current.state).toMatchObject({
        explanation: { text: "All factors text.", explanationSource: "ai" },
      });

      rerender({ factors: ["transit"] });
      act(() => vi.advanceTimersByTime(200));
      rerender({ factors: ["transit", "cafe"] });
      act(() => vi.advanceTimersByTime(399));
      expect(getAreaExplanation).toHaveBeenCalledTimes(1);
      expect(result.current.state).toMatchObject({
        explanation: { text: "All factors text.", updating: true },
      });

      act(() => vi.advanceTimersByTime(1));
      expect(getAreaExplanation).toHaveBeenCalledTimes(2);
      expect(getAreaExplanation.mock.calls[1][2]).toMatchObject({ factors: ["transit", "cafe"] });
      // Still the previous AI text, not the rules text.
      expect(result.current.state).toMatchObject({
        explanation: { text: "All factors text.", explanationSource: "ai", updating: true },
      });

      await act(async () => next.resolve(ai("Transit and cafe text.")));
      const state = result.current.state;
      expect(state).toMatchObject({
        explanation: { text: "Transit and cafe text.", explanationSource: "ai" },
      });
      expect(state.status === "success" && state.explanation).not.toHaveProperty("updating");
      expect(client.getAreaByCoordinates).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("uses priority-aware rules text for a narrowed selection, but not the default", async () => {
    vi.useFakeTimers();
    try {
      const rules = (text: string): AreaExplanation => ({
        explanation: text,
        source: "rules",
        areaId: 7,
        priorities: [],
      });
      const client = makeClient({
        getAreaByCoordinates: vi.fn(async () => makeAreaScore()),
        getAreaExplanation: vi
          .fn<ApiClient["getAreaExplanation"]>()
          .mockResolvedValueOnce(rules("Default rules from the AI endpoint."))
          .mockResolvedValueOnce(rules("Rules about transit.")),
      });
      const area = makeAreaScore();
      const { result, rerender } = renderHook(
        ({ factors }: { factors?: "transit"[] }) => useScoreLookup(click, client, { factors }),
        { initialProps: { factors: undefined as "transit"[] | undefined } },
      );
      await act(async () => {});
      expect(result.current.state).toMatchObject({ explanation: { text: area.explanation } });

      rerender({ factors: ["transit"] });
      await act(async () => vi.advanceTimersByTime(400));
      expect(result.current.state).toMatchObject({
        explanation: { text: "Rules about transit.", explanationSource: "rules" },
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it("passes the selection to the grid-square explanation too", async () => {
    const client = makeClient({
      getAreaByCoordinates: vi.fn(async () => Promise.reject(new ApiError("not-found", "n"))),
    });
    renderHook(() =>
      useScoreLookup(click, client, { factors: ["transit"], weights: { transit: 2 } }),
    );
    await waitFor(() => expect(client.getScoreExplanation).toHaveBeenCalled());
    expect(client.getScoreExplanation).toHaveBeenCalledWith(
      makeScore().geoEntityId,
      expect.objectContaining({ factors: ["transit"], weights: { transit: 2 } }),
    );
  });
});
