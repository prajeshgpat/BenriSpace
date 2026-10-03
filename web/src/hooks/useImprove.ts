"use client";

import type { ApiClient } from "@/lib/api/client";
import type { Improve, PriorityQuery } from "@/lib/api/types";

import {
  usePriorityResource,
  type PriorityResourceState,
} from "./usePriorityResource";

export type ImproveState = PriorityResourceState<Improve>;

const ALL: PriorityQuery = {};

/**
 * Loads "how could this area score higher" for a scored point and the user's
 * selected factors. Best effort: any failure is `unavailable` and the section
 * stays hidden; there is no retry. A stale response for a previous point is
 * never shown.
 */
export function useImprove(
  coordinates: { lat: number; lon: number } | null,
  client: Pick<ApiClient, "getImprove">,
  priorities: PriorityQuery = ALL,
): ImproveState {
  return usePriorityResource(coordinates, priorities, (lat, lon, query) =>
    client.getImprove(lat, lon, query),
  );
}
