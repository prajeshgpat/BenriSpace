import type { FactorKey, SubScores } from "@/lib/api/types";
import { buildCompositeSpec, cellComposite } from "@/lib/scores/matrix";

import { areaName, areaSubScores, findAreaIndex, type AreaScores } from "./areaScores";

/** What is known about an area before `GET /v1/area` answers. */
export interface ProvisionalArea {
  /** Normalised to the selected factors and weights, 0-100 like the map cells. */
  compositeScore: number;
  subScores: SubScores;
  neighborhood: string | null;
}

/**
 * The area's score from the static file, or `null` when the file does not
 * have it or none of the selected factors has a score there. The composite
 * uses the same arithmetic as the map cells (`cellComposite`).
 */
export function provisionalArea(
  areas: AreaScores,
  areaId: number,
  factors: readonly FactorKey[],
  weights: Partial<Record<FactorKey, number>> | undefined,
): ProvisionalArea | null {
  const index = findAreaIndex(areas, areaId);
  if (index === -1) return null;
  const composite = cellComposite(
    areas,
    index,
    buildCompositeSpec(areas, factors, weights),
  );
  if (composite === null) return null;
  return {
    compositeScore: Math.round(composite * 10) / 10,
    subScores: areaSubScores(areas, index),
    neighborhood: areaName(areas, index),
  };
}
