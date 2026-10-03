"use client";

import type { ApiClient } from "@/lib/api/client";
import type { PriorityQuery, Similar } from "@/lib/api/types";

import {
  usePriorityResource,
  type PriorityResourceState,
} from "./usePriorityResource";

export type SimilarState = PriorityResourceState<Similar>;

const ALL: PriorityQuery = {};

/** Areas elsewhere that look like this one for the selected factors. Best effort, like `useImprove`. */
export function useSimilar(
  coordinates: { lat: number; lon: number } | null,
  client: Pick<ApiClient, "getSimilar">,
  priorities: PriorityQuery = ALL,
): SimilarState {
  return usePriorityResource(coordinates, priorities, (lat, lon, query) =>
    client.getSimilar(lat, lon, query),
  );
}
