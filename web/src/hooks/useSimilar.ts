"use client";

import type { ApiClient } from "@/lib/api/client";
import type { PriorityQuery, Similar, SubScores } from "@/lib/api/types";
import type { AreaScores } from "@/lib/static/areaScores";
import { localSimilar } from "@/lib/static/similar";

import {
  usePriorityResource,
  type PriorityResourceState,
} from "./usePriorityResource";

export type SimilarState = PriorityResourceState<Similar>;

const ALL: PriorityQuery = {};

/** What lets the browser answer instead of the API (see `lib/static/similar.ts`). */
export interface LocalSimilarSource {
  areas: AreaScores | null;
  /** The place's own sub-scores. */
  subScores: SubScores | null;
  areaId?: number | null;
}

/**
 * Areas elsewhere that look like this one for the selected factors. Best
 * effort, like `useImprove`. Computed from the static area-score file when it
 * is loaded and the place is in it; the API answers otherwise.
 */
export function useSimilar(
  coordinates: { lat: number; lon: number } | null,
  client: Pick<ApiClient, "getSimilar">,
  priorities: PriorityQuery = ALL,
  local?: LocalSimilarSource,
): SimilarState {
  return usePriorityResource(coordinates, priorities, async (lat, lon, query) => {
    if (local?.areas && local.subScores) {
      try {
        const result = localSimilar(local.areas, {
          lat,
          lon,
          source: local.subScores,
          areaId: local.areaId,
          factors: query.factors,
          weights: query.weights,
        });
        if (result) return result;
      } catch {
        // Fall through to the API.
      }
    }
    return client.getSimilar(lat, lon, query);
  });
}
