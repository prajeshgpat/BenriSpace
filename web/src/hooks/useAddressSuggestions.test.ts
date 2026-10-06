import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ApiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { Suggestion } from "@/lib/api/types";

import {
  SUGGEST_DEBOUNCE_MS,
  useAddressSuggestions,
} from "./useAddressSuggestions";

const A: Suggestion = {
  label: "350 5th Avenue, New York, NY",
  latitude: 40.7484,
  longitude: -73.9857,
};

type Suggest = ApiClient["suggestAddresses"];

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

const settle = () =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(SUGGEST_DEBOUNCE_MS);
  });

describe("useAddressSuggestions", () => {
  it("waits for the debounce, then makes one request for the final text", async () => {
    const suggestAddresses = vi.fn<Suggest>(async () => [A]);
    const { result } = renderHook(() =>
      useAddressSuggestions({ suggestAddresses }),
    );

    act(() => result.current.handleInput("350"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    act(() => result.current.handleInput("350 5"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    act(() => result.current.handleInput("350 5th"));
    expect(suggestAddresses).not.toHaveBeenCalled();

    await settle();

    expect(suggestAddresses).toHaveBeenCalledTimes(1);
    expect(suggestAddresses).toHaveBeenCalledWith(
      "350 5th",
      expect.objectContaining({ limit: 8, signal: expect.any(AbortSignal) }),
    );
    expect(result.current.open).toBe(true);
    expect(result.current.state.suggestions).toEqual([A]);
  });

  it("does not request below 3 characters", async () => {
    const suggestAddresses = vi.fn<Suggest>(async () => [A]);
    const { result } = renderHook(() =>
      useAddressSuggestions({ suggestAddresses }),
    );

    act(() => result.current.handleInput("35"));
    await settle();

    expect(suggestAddresses).not.toHaveBeenCalled();
  });

  it("does nothing without a client", async () => {
    const { result } = renderHook(() => useAddressSuggestions(null));
    act(() => result.current.handleInput("350 5th"));
    await settle();
    expect(result.current.open).toBe(false);
  });

  it("aborts the in-flight request when the text changes and drops its result", async () => {
    const first = deferred<Suggestion[]>();
    const signals: AbortSignal[] = [];
    const suggestAddresses = vi.fn<Suggest>((_query, options) => {
      signals.push(options!.signal!);
      return signals.length === 1 ? first.promise : Promise.resolve([]);
    });
    const { result } = renderHook(() =>
      useAddressSuggestions({ suggestAddresses }),
    );

    act(() => result.current.handleInput("350 5th"));
    await settle();
    act(() => result.current.handleInput("350 5th av"));
    expect(signals[0].aborted).toBe(true);

    await act(async () => first.resolve([A]));
    expect(result.current.state.suggestions).toEqual([]);
  });

  it("ignores a late response that was not aborted but is for old text", async () => {
    const first = deferred<Suggestion[]>();
    const second = deferred<Suggestion[]>();
    const pending = [first, second];
    const suggestAddresses = vi.fn<Suggest>(() => pending.shift()!.promise);
    const { result } = renderHook(() =>
      useAddressSuggestions({ suggestAddresses }),
    );

    act(() => result.current.handleInput("350 5th"));
    await settle();
    act(() => result.current.handleInput("350 5th av"));
    await settle();

    await act(async () => second.resolve([A]));
    await act(async () => first.resolve([{ ...A, label: "stale" }]));

    expect(result.current.state.suggestions).toEqual([A]);
  });

  it("fails silently on an API error", async () => {
    const suggestAddresses = vi.fn<Suggest>(async () => {
      throw new ApiError("server", "unavailable", { status: 503 });
    });
    const { result } = renderHook(() =>
      useAddressSuggestions({ suggestAddresses }),
    );

    act(() => result.current.handleInput("350 5th"));
    await settle();

    expect(result.current.open).toBe(false);
    expect(result.current.state.suggestions).toEqual([]);
  });

  it("fails silently on a network error", async () => {
    const suggestAddresses = vi.fn<Suggest>(async () => {
      throw new ApiError("network", "offline");
    });
    const { result } = renderHook(() =>
      useAddressSuggestions({ suggestAddresses }),
    );

    act(() => result.current.handleInput("350 5th"));
    await settle();

    expect(result.current.open).toBe(false);
  });

  it("reset cancels a pending debounce so a programmatic fill never looks anything up", async () => {
    const suggestAddresses = vi.fn<Suggest>(async () => [A]);
    const { result } = renderHook(() =>
      useAddressSuggestions({ suggestAddresses }),
    );

    act(() => result.current.handleInput("350 5th"));
    act(() => result.current.reset());
    await settle();

    expect(suggestAddresses).not.toHaveBeenCalled();
    expect(result.current.open).toBe(false);
  });

  it("does not repeat a request for the same normalised text", async () => {
    const suggestAddresses = vi.fn<Suggest>(async () => [A]);
    const { result } = renderHook(() =>
      useAddressSuggestions({ suggestAddresses }),
    );

    act(() => result.current.handleInput("350 5th"));
    await settle();
    act(() => result.current.handleInput("350  5th "));
    await settle();

    expect(suggestAddresses).toHaveBeenCalledTimes(1);
  });

  it("aborts on unmount", async () => {
    const pending = deferred<Suggestion[]>();
    let signal: AbortSignal | undefined;
    const suggestAddresses = vi.fn<Suggest>((_q, options) => {
      signal = options?.signal;
      return pending.promise;
    });
    const { result, unmount } = renderHook(() =>
      useAddressSuggestions({ suggestAddresses }),
    );

    act(() => result.current.handleInput("350 5th"));
    await settle();
    unmount();

    expect(signal?.aborted).toBe(true);
  });
});
