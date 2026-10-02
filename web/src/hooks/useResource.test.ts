import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/errors";

import { useResource } from "./useResource";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("useResource", () => {
  it("is idle and does not fetch without a key", () => {
    const fetcher = vi.fn();
    const { result } = renderHook(() => useResource(null, fetcher));
    expect(result.current.status).toBe("idle");
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("loads, then exposes the data", async () => {
    const { result } = renderHook(() => useResource("a", async () => 1));
    expect(result.current.status).toBe("loading");
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.data).toBe(1);
  });

  it("keeps the previous data visible while the next key loads", async () => {
    const next = deferred<number>();
    const { result, rerender } = renderHook(
      ({ key }) =>
        useResource(key, () =>
          key === "a" ? Promise.resolve(1) : next.promise,
        ),
      { initialProps: { key: "a" } },
    );
    await waitFor(() => expect(result.current.data).toBe(1));

    rerender({ key: "b" });

    expect(result.current).toMatchObject({ status: "loading", data: 1 });
    await act(async () => next.resolve(2));
    expect(result.current).toMatchObject({ status: "ready", data: 2 });
  });

  it("aborts the superseded request and ignores its result", async () => {
    const first = deferred<number>();
    const signals: AbortSignal[] = [];
    const { result, rerender } = renderHook(
      ({ key }) =>
        useResource(key, (signal) => {
          signals.push(signal);
          return key === "a" ? first.promise : Promise.resolve(2);
        }),
      { initialProps: { key: "a" } },
    );

    rerender({ key: "b" });
    await waitFor(() => expect(result.current.data).toBe(2));
    expect(signals[0].aborted).toBe(true);

    await act(async () => first.resolve(1));
    expect(result.current.data).toBe(2);
  });

  it("reports an error but keeps the last data, and retries", async () => {
    const fetcher = vi
      .fn<() => Promise<number>>()
      .mockResolvedValueOnce(1)
      .mockRejectedValueOnce(
        new ApiError("rate-limited", "slow down", { status: 429 }),
      )
      .mockResolvedValueOnce(3);
    const { result, rerender } = renderHook(
      ({ key }) => useResource(key, fetcher),
      {
        initialProps: { key: "a" },
      },
    );
    await waitFor(() => expect(result.current.data).toBe(1));

    rerender({ key: "b" });
    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error?.kind).toBe("rate-limited");
    expect(result.current.data).toBe(1);

    act(() => result.current.retry());
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.data).toBe(3);
  });

  it("drops the data when the key becomes null", async () => {
    const { result, rerender } = renderHook(
      ({ key }: { key: string | null }) => useResource(key, async () => 1),
      { initialProps: { key: "a" as string | null } },
    );
    await waitFor(() => expect(result.current.data).toBe(1));

    rerender({ key: null });

    expect(result.current).toMatchObject({ status: "idle", data: null });
  });
});
