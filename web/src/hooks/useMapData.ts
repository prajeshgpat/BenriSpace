"use client";

import { useMemo, useState } from "react";

import type { Viewport } from "@/components/map/MapCanvas";
import { useResource } from "@/hooks/useResource";
import type { ApiClient } from "@/lib/api/client";
import { EMPTY_CELLS, cellsToFeatures, scoreRange } from "@/lib/map/features";
import {
  isAllSelected,
  learnDefaults,
  resolveWeights,
  type DefaultWeights,
  type FactorSelection,
} from "@/lib/map/selection";
import type { TopScope } from "@/lib/map/url";
import {
  CELL_LIMIT,
  bboxKey,
  padBbox,
  precisionForZoom,
  roundBbox,
} from "@/lib/map/viewport";

const TOP_LIMIT = 10;
/** A zoomed-in view holds a neighbourhood, where 3 km would leave one result. */
const VIEW_SCOPE_SEPARATION_KM = 1;

interface MapDataInput {
  client: ApiClient;
  selection: FactorSelection;
  scope: TopScope;
  viewport: Viewport | null;
  /** The view the user chose, which "this view only" follows. */
  topViewport: Viewport | null;
}

/** The colored cells for the viewport and the ranked best areas. */
export function useMapData({
  client,
  selection,
  scope,
  viewport,
  topViewport,
}: MapDataInput) {
  const [defaults, setDefaults] = useState<DefaultWeights>({});

  const noFactors = selection.factors.length === 0;
  const weights = useMemo(
    () => resolveWeights(selection, defaults),
    [selection, defaults],
  );
  const factorsParam = isAllSelected(selection) ? undefined : selection.factors;
  const selectionKey = `${selection.factors.join(",")}|${JSON.stringify(weights ?? {})}`;

  const cellBbox = useMemo(
    () => (viewport ? roundBbox(padBbox(viewport.bbox)) : null),
    [viewport],
  );
  const cellsKey =
    !noFactors && viewport && cellBbox
      ? `${bboxKey(cellBbox)}|${precisionForZoom(viewport.zoom)}|${selectionKey}`
      : null;

  const cells = useResource(cellsKey, async (signal) => {
    if (!viewport || !cellBbox) throw new Error("unreachable");
    const result = await client.getMapCells(
      {
        bbox: cellBbox,
        precision: precisionForZoom(viewport.zoom),
        factors: factorsParam,
        weights,
        limit: CELL_LIMIT,
      },
      { signal },
    );
    setDefaults((known) => learnDefaults(known, result.weights, weights));
    return result;
  });

  const viewBbox =
    scope === "view" && topViewport ? roundBbox(topViewport.bbox) : undefined;
  const topKey = noFactors
    ? null
    : `${viewBbox ? bboxKey(viewBbox) : "metro"}|${selectionKey}`;

  const top = useResource(topKey, async (signal) => {
    const result = await client.getMapTop(
      {
        bbox: viewBbox,
        factors: factorsParam,
        weights,
        limit: TOP_LIMIT,
        minSeparationKm: viewBbox ? VIEW_SCOPE_SEPARATION_KM : undefined,
      },
      { signal },
    );
    setDefaults((known) => learnDefaults(known, result.weights, weights));
    return result;
  });

  const features = useMemo(
    () =>
      cells.data && !noFactors ? cellsToFeatures(cells.data) : EMPTY_CELLS,
    [cells.data, noFactors],
  );
  const range = useMemo(
    () => (cells.data && !noFactors ? scoreRange(cells.data.scores) : null),
    [cells.data, noFactors],
  );
  const topResults = useMemo(
    () => (noFactors ? null : (top.data?.results ?? null)),
    [top.data, noFactors],
  );

  return { noFactors, cells, top, features, range, topResults };
}
