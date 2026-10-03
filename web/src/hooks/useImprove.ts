"use client";

import type { ApiClient } from "@/lib/api/client";
import type { Improve } from "@/lib/api/types";

import { useResource } from "./useResource";

export interface ImproveState {
  status: "idle" | "loading" | "ready" | "unavailable";
  data: Improve | null;
}

/**
 * Loads "how could this area score higher" for a scored point. Best effort:
 * any failure is `unavailable` and the section stays hidden; there is no
 * retry. A stale response for a previous point is never shown.
 */
export function useImprove(
  coordinates: { lat: number; lon: number } | null,
  client: Pick<ApiClient, "getImprove">,
): ImproveState {
  const key =
    coordinates === null ? null : `${coordinates.lat},${coordinates.lon}`;
  const resource = useResource<Improve>(key, (signal) =>
    client.getImprove((coordinates as { lat: number }).lat, (coordinates as { lon: number }).lon, signal),
  );

  if (key === null || resource.status === "idle") {
    return { status: "idle", data: null };
  }
  if (resource.status === "error") return { status: "unavailable", data: null };
  if (resource.status === "ready" && resource.data) {
    return { status: "ready", data: resource.data };
  }
  // useResource keeps the previous point's data while loading; don't show it.
  return { status: "loading", data: null };
}
