import type { FactorKey, MapTopResult } from "@/lib/api/types";
import { buildCompositeSpec, compositeAll } from "@/lib/scores/matrix";
import { localTop, type Rankable, type TopOptions } from "@/lib/scores/topk";

import { areaMetro, areaName, type AreaScores } from "./areaScores";

/** Prefix of a ranked area's key; it stands in for the geohash a ranked cell has. */
export const AREA_KEY_PREFIX = "area:";

export function areaKey(id: number): string {
  return `${AREA_KEY_PREFIX}${id}`;
}

const rankables = new WeakMap<AreaScores, Rankable>();

/** The area file in the shape `localTop` ranks; keys sort by id for ties. */
function asRankable(areas: AreaScores): Rankable {
  let rankable = rankables.get(areas);
  if (!rankable) {
    const width = String(areas.ids[areas.count - 1] ?? 0).length;
    const keys = Array.from(
      areas.ids,
      (id) => `${AREA_KEY_PREFIX}${String(id).padStart(width, "0")}`,
    );
    rankable = { ...areas, geohashes: keys };
    rankables.set(areas, rankable);
  }
  return rankable;
}

/** One composite per area, the same arithmetic as the map cells; `NaN` when unscored. */
export function areaComposites(
  areas: AreaScores,
  factors: readonly FactorKey[],
  weights: Partial<Record<FactorKey, number>> | undefined,
  defaults: Partial<Record<FactorKey, number>> = {},
): Float64Array {
  return compositeAll(areas, buildCompositeSpec(areas, factors, weights, defaults));
}

/**
 * The best road-bounded areas, spaced out like the cell ranking. Each result's
 * score is the area's own composite, which is what its score card shows, so
 * the map marker, the list row and the card agree.
 */
export function localTopAreas(
  areas: AreaScores,
  composites: Float64Array,
  options: TopOptions,
): MapTopResult[] {
  const rankable = asRankable(areas);
  const indexOf = new Map(rankable.geohashes.map((key, i) => [key, i]));
  return localTop(rankable, composites, options).map((result) => {
    const i = indexOf.get(result.geohash) ?? -1;
    const id = areas.ids[i];
    return {
      ...result,
      geohash: areaKey(id),
      areaId: id,
      neighborhood: areaName(areas, i),
      metroArea: areaMetro(areas, i) ?? "",
    };
  });
}
