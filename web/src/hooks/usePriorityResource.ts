"use client";

import type { PriorityQuery } from "@/lib/api/types";
import { hasNoFactors, priorityKey } from "@/lib/map/selection";

import { useDebouncedValue } from "./useDebouncedValue";
import { useResource } from "./useResource";

export interface PriorityResourceState<T> {
  status: "idle" | "loading" | "ready" | "unavailable";
  data: T | null;
  /** The data on screen is for the previous selection; a new one is on its way. */
  updating: boolean;
}

/**
 * Loads something about a point for the user's selected factors. A new point
 * clears the old result at once; a new selection (debounced, so toggling
 * several pills sends one request) keeps the old result in place, marked
 * `updating`, until the new one arrives. Failures are `unavailable`, and with
 * no factors selected nothing is requested.
 */
export function usePriorityResource<T>(
  coordinates: { lat: number; lon: number } | null,
  priorities: PriorityQuery,
  fetcher: (
    lat: number,
    lon: number,
    query: PriorityQuery & { signal: AbortSignal },
  ) => Promise<T>,
): PriorityResourceState<T> {
  const liveKey = priorityKey(priorities);
  const debounced = useDebouncedValue(priorities, liveKey);
  const debouncedKey = priorityKey(debounced);

  const pointKey =
    coordinates === null ? null : `${coordinates.lat},${coordinates.lon}`;
  const disabled = hasNoFactors(priorities);
  const key =
    pointKey === null || disabled ? null : `${pointKey}|${debouncedKey}`;

  const resource = useResource<{ pointKey: string; data: T }>(
    key,
    async (signal) => {
      const { lat, lon } = coordinates as { lat: number; lon: number };
      const data = await fetcher(lat, lon, {
        factors: debounced.factors,
        weights: debounced.weights,
        signal,
      });
      return { pointKey: pointKey as string, data };
    },
  );

  if (key === null || resource.status === "idle") {
    return { status: "idle", data: null, updating: false };
  }
  if (resource.status === "error") {
    return { status: "unavailable", data: null, updating: false };
  }
  // useResource keeps the last result while loading; only the same point's
  // counts, otherwise it would be another place's answer.
  const current = resource.data?.pointKey === pointKey ? resource.data : null;
  if (!current) return { status: "loading", data: null, updating: false };
  return {
    status: "ready",
    data: current.data,
    updating: resource.status === "loading" || liveKey !== debouncedKey,
  };
}
