"use client";

import type { ApiClient, Coordinates } from "@/lib/api/client";

import { useResource } from "./useResource";

export type ReverseGeocodeStatus = "idle" | "loading" | "ready" | "unavailable";

export interface ReverseGeocodeResult {
  /** Null while loading, when nothing usable is known, and on any failure. */
  label: string | null;
  status: ReverseGeocodeStatus;
}

const CACHE_MAX_ENTRIES = 200;
// Insertion-ordered, so the oldest entry is first. Only successful answers
// (including "no usable address") are stored; failures are retried.
const cache = new Map<string, string | null>();

export function reverseCacheKey({ lat, lon }: Coordinates): string {
  return `${lat.toFixed(4)},${lon.toFixed(4)}`;
}

/** Test helper. */
export function clearReverseGeocodeCache(): void {
  cache.clear();
}

function remember(key: string, label: string | null): void {
  cache.delete(key);
  cache.set(key, label);
  if (cache.size > CACHE_MAX_ENTRIES) {
    const oldest = cache.keys().next();
    if (!oldest.done) cache.delete(oldest.value);
  }
}

/**
 * Resolves a map point to a readable address. Best effort: every failure
 * (offline, 503, out of coverage, timeout) yields `label: null` with status
 * "unavailable", never an error to show, so callers fall back to coordinates.
 */
export function useReverseGeocode(
  coordinates: Coordinates | null,
  client: Pick<ApiClient, "reverseGeocode">,
): ReverseGeocodeResult {
  const key = coordinates === null ? null : reverseCacheKey(coordinates);
  const hit = key !== null && cache.has(key);

  const resource = useResource<string | null>(
    key !== null && !hit ? key : null,
    async (signal) => {
      const { label } = await client.reverseGeocode(coordinates as Coordinates, {
        signal,
      });
      remember(key as string, label);
      return label;
    },
  );

  if (key === null) return { label: null, status: "idle" };
  if (hit) return { label: cache.get(key) ?? null, status: "ready" };
  if (resource.status === "error") return { label: null, status: "unavailable" };
  if (resource.status === "ready") return { label: resource.data, status: "ready" };
  // useResource keeps the previous point's data while loading; don't show it.
  return { label: null, status: "loading" };
}
