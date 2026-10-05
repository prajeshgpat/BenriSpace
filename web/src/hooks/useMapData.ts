"use client";

import { useMemo, useState } from "react";

import { useScoreMatrix } from "@/hooks/useScoreMatrix";
import {
  DEFAULT_FACTOR_WEIGHTS,
  buildCompositeSpec,
  compositeAll,
  localCells,
} from "@/lib/scores/matrix";
import { localTop } from "@/lib/scores/topk";
import type { AreaScores } from "@/lib/static/areaScores";
import { areaComposites, localTopAreas } from "@/lib/static/topAreas";
import type { MapCells, MapTopResult } from "@/lib/api/types";
import { boundsToFeatures } from "@/lib/map/features";

import type { Viewport } from "@/components/map/MapCanvas";
import { useResource, type Resource } from "@/hooks/useResource";
import type { ApiClient } from "@/lib/api/client";
import { EMPTY_CELLS, cellsToFeatures, scoreRange } from "@/lib/map/features";
import {
  priorityQuery,
  learnDefaults,
  resolveWeights,
  type DefaultWeights,
  type FactorSelection,
} from "@/lib/map/selection";
import {
  CELL_LIMIT,
  bboxKey,
  padBbox,
  precisionForZoom,
  roundBbox,
} from "@/lib/map/viewport";

const TOP_LIMIT = 10;
/** The API's own default spacing (3 km) when the best-areas list has no viewport. */
const METRO_SEPARATION_MI = 3 / 1.609344;
interface Names {
  [geohash: string]: { neighborhood: string | null; metroArea: string };
}
const noop = () => {};
/** A zoomed-in view holds a neighbourhood, where 2 mi would leave one result. */
const VIEW_SEPARATION_MI = 0.6;

interface MapDataInput {
  client: ApiClient;
  selection: FactorSelection;
  viewport: Viewport | null;
  /** The view the user chose, which the best-areas list follows. */
  topViewport: Viewport | null;
  /**
   * The vector-tile grid draws the cells, so locally scored cells need no
   * GeoJSON (the map reads `tileCells` instead).
   */
  tiles?: boolean;
  /**
   * Every road-bounded area's sub-scores (R2). When present the best-areas
   * list ranks areas, not cells, so a marker's score is the score its card shows.
   */
  areaScores?: AreaScores | null;
}

/** The colored cells for the viewport and the ranked best areas. */
export function useMapData({
  client,
  selection,
  viewport,
  topViewport,
  tiles = false,
  areaScores = null,
}: MapDataInput) {
  const [defaults, setDefaults] = useState<DefaultWeights>({});
  const [names, setNames] = useState<Names>({});
  const matrixState = useScoreMatrix(client);
  const matrix = matrixState.matrix;

  const noFactors = selection.factors.length === 0;
  // With the score file the defaults are known up front; the server's own
  // numbers, once seen, still win.
  const weights = useMemo(
    () =>
      resolveWeights(
        selection,
        matrix ? { ...DEFAULT_FACTOR_WEIGHTS, ...defaults } : defaults,
      ),
    [selection, defaults, matrix],
  );
  const composites = useMemo(() => {
    if (!matrix || selection.factors.length === 0) return null;
    return compositeAll(
      matrix,
      buildCompositeSpec(matrix, selection.factors, weights, defaults),
    );
  }, [matrix, selection.factors, weights, defaults]);
  const local = composites !== null;
  const factorsParam = priorityQuery(selection, weights).factors;
  const selectionKey = `${selection.factors.join(",")}|${JSON.stringify(weights ?? {})}`;

  const cellBbox = useMemo(
    () => (viewport ? roundBbox(padBbox(viewport.bbox)) : null),
    [viewport],
  );
  const cellsKey =
    !noFactors && !local && viewport && cellBbox
      ? `${bboxKey(cellBbox)}|${precisionForZoom(viewport.zoom)}|${selectionKey}`
      : null;

  const apiCells = useResource(cellsKey, async (signal) => {
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
    topViewport ? roundBbox(topViewport.bbox) : undefined;
  const viewKey = viewBbox ? bboxKey(viewBbox) : "metro";
  // Ranking is local once the score file is in, so the API is asked only for
  // names, and only when a ranked area has not been named yet.
  const areaComposite = useMemo(() => {
    if (!areaScores || selection.factors.length === 0) return null;
    return areaComposites(areaScores, selection.factors, weights, defaults);
  }, [areaScores, selection.factors, weights, defaults]);
  const localResults = useMemo(() => {
    const options = {
      bbox: viewBbox,
      limit: TOP_LIMIT,
      minSeparationMi: viewBbox ? VIEW_SEPARATION_MI : METRO_SEPARATION_MI,
    };
    // Areas carry their own names, so ranking them needs no API call at all.
    if (areaScores && areaComposite) {
      return localTopAreas(areaScores, areaComposite, options);
    }
    if (!matrix || !composites) return null;
    return localTop(matrix, composites, options);
    // viewBbox is rebuilt each render; its key is the identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matrix, composites, areaScores, areaComposite, viewKey]);
  const needsNames =
    localResults !== null &&
    localResults.some((r) => r.areaId === undefined && !(r.geohash in names));
  const topKey = noFactors || (localResults !== null && !needsNames)
    ? null
    : `${viewKey}|${selectionKey}`;

  const top = useResource(topKey, async (signal) => {
    const result = await client.getMapTop(
      {
        bbox: viewBbox,
        factors: factorsParam,
        weights,
        limit: TOP_LIMIT,
        minSeparationMi: viewBbox ? VIEW_SEPARATION_MI : undefined,
      },
      { signal },
    );
    setDefaults((known) => learnDefaults(known, result.weights, weights));
    // Names for locally ranked areas come from here.
    setNames((known) => ({
      ...known,
      ...Object.fromEntries(
        result.results.map((r) => [
          r.geohash,
          { neighborhood: r.neighborhood ?? null, metroArea: r.metroArea },
        ]),
      ),
    }));
    return result;
  });

  const localCellData = useMemo(() => {
    if (!matrix || !composites || !cellBbox || !viewport) return null;
    return localCells(
      matrix,
      cellBbox,
      precisionForZoom(viewport.zoom),
      composites,
    );
  }, [matrix, composites, cellBbox, viewport]);

  const cells: Resource<MapCells> = useMemo(() => {
    if (!localCellData || !viewport) return apiCells;
    return {
      status: "ready",
      error: null,
      retry: noop,
      data: {
        precision: precisionForZoom(viewport.zoom),
        factors: [...selection.factors],
        weights: weights ?? {},
        weightsVersion: String(matrix?.header.version ?? ""),
        truncated: false,
        geohashes: localCellData.geohashes,
        scores: localCellData.scores,
      },
    };
  }, [localCellData, viewport, apiCells, selection.factors, weights, matrix]);

  const features = useMemo(() => {
    if (noFactors) return EMPTY_CELLS;
    if (localCellData) return tiles ? EMPTY_CELLS : boundsToFeatures(localCellData);
    return cells.data ? cellsToFeatures(cells.data) : EMPTY_CELLS;
  }, [cells.data, noFactors, localCellData, tiles]);
  const range = useMemo(
    () => (cells.data && !noFactors ? scoreRange(cells.data.scores) : null),
    [cells.data, noFactors],
  );
  const tileCells = useMemo(
    () =>
      localCellData && viewport
        ? {
            precision: precisionForZoom(viewport.zoom),
            geohashes: localCellData.geohashes,
            scores: localCellData.scores,
          }
        : null,
    [localCellData, viewport],
  );
  const topResults = useMemo((): MapTopResult[] | null => {
    if (noFactors) return null;
    if (!localResults) return top.data?.results ?? null;
    const lookupDone = top.status === "ready" || top.status === "error";
    return localResults.map((r) => {
      if (r.areaId !== undefined) return r;
      const known = names[r.geohash];
      if (known) return { ...r, ...known };
      return lookupDone ? r : { ...r, namePending: true };
    });
  }, [noFactors, localResults, top.data, top.status, names]);
  const topState = localResults
    ? { ...top, status: "ready" as const, error: null, retry: noop }
    : top;

  return {
    noFactors,
    cells,
    top: topState,
    features,
    range,
    topResults,
    weights,
    local,
    tileCells: noFactors ? null : tileCells,
  };
}
