import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/errors";

import {
  clearReverseGeocodeCache,
  reverseCacheKey,
  useReverseGeocode,
} from "./useReverseGeocode";

const POINT = { lat: 40.7314, lon: -74.0635 };
const LABEL = "9 Journal Square Concourse, Jersey City, NJ";

function clientWith(impl: () => Promise<{ label: string | null }>) {
  const reverseGeocode = vi.fn(async () => {
    const { label } = await impl();
    return { label, latitude: POINT.lat, longitude: POINT.lon };
  });
  return { reverseGeocode };
}

beforeEach(() => clearReverseGeocodeCache());

describe("useReverseGeocode", () => {
  it("is idle without coordinates and never calls the API", () => {
    const client = clientWith(async () => ({ label: LABEL }));
    const { result } = renderHook(() => useReverseGeocode(null, client));
    expect(result.current).toEqual({ label: null, status: "idle" });
    expect(client.reverseGeocode).not.toHaveBeenCalled();
  });

  it("loads, then exposes the label", async () => {
    const client = clientWith(async () => ({ label: LABEL }));
    const { result } = renderHook(() => useReverseGeocode(POINT, client));
    expect(result.current).toEqual({ label: null, status: "loading" });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.label).toBe(LABEL);
  });

  it("serves repeat points (same 4 decimals) from the cache", async () => {
    const client = clientWith(async () => ({ label: LABEL }));
    const first = renderHook(() => useReverseGeocode(POINT, client));
    await waitFor(() => expect(first.result.current.status).toBe("ready"));

    const nearby = { lat: 40.731402, lon: -74.063498 };
    expect(reverseCacheKey(nearby)).toBe(reverseCacheKey(POINT));
    const second = renderHook(() => useReverseGeocode(nearby, client));
    expect(second.result.current).toEqual({ label: LABEL, status: "ready" });
    expect(client.reverseGeocode).toHaveBeenCalledTimes(1);
  });

  it("caches a null label (no usable address) too", async () => {
    const client = clientWith(async () => ({ label: null }));
    const first = renderHook(() => useReverseGeocode(POINT, client));
    await waitFor(() => expect(first.result.current.status).toBe("ready"));
    const second = renderHook(() => useReverseGeocode(POINT, client));
    expect(second.result.current).toEqual({ label: null, status: "ready" });
    expect(client.reverseGeocode).toHaveBeenCalledTimes(1);
  });

  it("degrades to a null label on failure and retries later", async () => {
    let fail = true;
    const client = clientWith(async () => {
      if (fail) throw new ApiError("server", "down", { status: 503 });
      return { label: LABEL };
    });
    const first = renderHook(() => useReverseGeocode(POINT, client));
    await waitFor(() => expect(first.result.current.status).toBe("unavailable"));
    expect(first.result.current.label).toBeNull();

    fail = false;
    const second = renderHook(() => useReverseGeocode(POINT, client));
    await waitFor(() => expect(second.result.current.label).toBe(LABEL));
    expect(client.reverseGeocode).toHaveBeenCalledTimes(2);
  });

  it("does not show the previous point's label while the next loads", async () => {
    const other = { lat: 40.75, lon: -73.99 };
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    const client = clientWith(async () => {
      await gate;
      return { label: "Other St, New York, NY" };
    });
    const { result, rerender } = renderHook(
      ({ point }) => useReverseGeocode(point, client),
      { initialProps: { point: POINT } },
    );
    release();
    await waitFor(() => expect(result.current.status).toBe("ready"));
    rerender({ point: other });
    expect(result.current.label).toBeNull();
    expect(result.current.status).not.toBe("ready");
  });
});
