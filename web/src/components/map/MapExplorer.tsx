"use client";

import {
  useEffect,
  useId,
  useMemo,
  useState,
  useSyncExternalStore,
} from "react";

import { useResource } from "@/hooks/useResource";
import { createApiClient, type ApiClient } from "@/lib/api/client";
import { describeError } from "@/lib/api/messages";
import type { MapTopResult } from "@/lib/api/types";
import { API_BASE_URL } from "@/lib/config";
import { EMPTY_CELLS, cellsToFeatures, scoreRange } from "@/lib/map/features";
import {
  areaTitle,
  describeMapStatus,
  formatCount,
} from "@/lib/map/presentation";
import {
  isAllSelected,
  learnDefaults,
  resolveWeights,
  type DefaultWeights,
  type FactorSelection,
} from "@/lib/map/selection";
import {
  serializeMapParams,
  type MapUrlState,
  type TopScope,
} from "@/lib/map/url";
import {
  CELL_LIMIT,
  bboxKey,
  padBbox,
  precisionForZoom,
  roundBbox,
} from "@/lib/map/viewport";
import { FACTORS } from "@/lib/score/factors";

import { AreaDetails } from "./AreaDetails";
import { BestAreas } from "./BestAreas";
import { FactorControls } from "./FactorControls";
import {
  MapCanvas,
  type CellClick,
  type FlyRequest,
  type MarkerSpec,
  type PopupSpec,
  type Viewport,
} from "./MapCanvas";
import { MapLegend } from "./MapLegend";
import styles from "./MapExplorer.module.css";

const defaultClient = createApiClient({ baseUrl: API_BASE_URL });

const TOP_LIMIT = 10;
const POPUP_MAX_ROWS = 5;
/** A zoomed-in view holds a neighbourhood, where 3 km would leave one result. */
const VIEW_SCOPE_SEPARATION_KM = 1;

type Selected =
  { kind: "top"; geohash: string } | ({ kind: "cell" } & CellClick);

const DESKTOP_QUERY = "(min-width: 48rem)";

function subscribeToDesktop(onChange: () => void) {
  const query = window.matchMedia(DESKTOP_QUERY);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

function useIsDesktop(): boolean {
  return useSyncExternalStore(
    subscribeToDesktop,
    () => window.matchMedia(DESKTOP_QUERY).matches,
    () => true,
  );
}

interface MapExplorerProps {
  initial: MapUrlState;
  client?: ApiClient;
}

export function MapExplorer({
  initial,
  client = defaultClient,
}: MapExplorerProps) {
  const [selection, setSelection] = useState<FactorSelection>(
    initial.selection,
  );
  const [scope, setScope] = useState<TopScope>(initial.scope);
  const [defaults, setDefaults] = useState<DefaultWeights>({});
  const [viewport, setViewport] = useState<Viewport | null>(null);
  // "This view only" follows what the user is looking at, not the app's own
  // fly-to moves, which would otherwise re-rank the list under their cursor.
  const [topViewport, setTopViewport] = useState<Viewport | null>(null);
  const [selected, setSelected] = useState<Selected | null>(null);
  const [flyRequest, setFlyRequest] = useState<FlyRequest | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [mapUnavailable, setMapUnavailable] = useState(false);

  const desktop = useIsDesktop();
  const bodyId = useId();

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

  const markers = useMemo<MarkerSpec[]>(
    () =>
      (topResults ?? []).map((result, index) => ({
        id: result.geohash,
        rank: index + 1,
        lat: result.latitude,
        lon: result.longitude,
        label: `Rank ${index + 1}, score ${Math.round(result.score)}. Show details`,
      })),
    [topResults],
  );

  const activeTop =
    selected?.kind === "top"
      ? (topResults?.find((r) => r.geohash === selected.geohash) ?? null)
      : null;

  const popup = useMemo<PopupSpec | null>(() => {
    if (activeTop && topResults) {
      const rank = topResults.indexOf(activeTop) + 1;
      return {
        lat: activeTop.latitude,
        lon: activeTop.longitude,
        children: (
          <AreaDetails
            title={`#${rank} · ${areaTitle(activeTop)}`}
            score={activeTop.score}
            basis={`${selection.factors.length} selected ${selection.factors.length === 1 ? "factor" : "factors"}`}
            rows={selection.factors.map((key) => ({
              key,
              label: FACTORS[key].label,
              value: activeTop.subScores[key],
            }))}
            maxRows={POPUP_MAX_ROWS}
            lat={activeTop.latitude}
            lon={activeTop.longitude}
          />
        ),
      };
    }
    if (selected?.kind === "cell") {
      return {
        lat: selected.lat,
        lon: selected.lon,
        children: (
          <AreaDetails
            title="Map cell"
            score={selected.score}
            basis={`${selection.factors.length} selected ${selection.factors.length === 1 ? "factor" : "factors"}`}
            rows={[]}
            lat={selected.lat}
            lon={selected.lon}
          />
        ),
      };
    }
    return null;
  }, [activeTop, topResults, selected, selection.factors]);

  const highlightGeohash =
    selected?.kind === "cell" ? selected.geohash : (activeTop?.geohash ?? null);

  // The URL mirrors the view and filters so any state can be shared. It is
  // only written, never read back, after the first render.
  const view = viewport
    ? {
        lat: viewport.center.lat,
        lon: viewport.center.lon,
        zoom: viewport.zoom,
      }
    : initial.view;
  const viewLat = view?.lat;
  const viewLon = view?.lon;
  const viewZoom = view?.zoom;
  useEffect(() => {
    const query = serializeMapParams({
      view:
        viewLat === undefined || viewLon === undefined || viewZoom === undefined
          ? null
          : { lat: viewLat, lon: viewLon, zoom: viewZoom },
      selection,
      scope,
    });
    window.history.replaceState(null, "", query ? `/map?${query}` : "/map");
  }, [viewLat, viewLon, viewZoom, selection, scope]);

  function selectTop(result: MapTopResult) {
    if (selected?.kind === "top" && selected.geohash === result.geohash) {
      setSelected(null);
      return;
    }
    setSelected({ kind: "top", geohash: result.geohash });
    setFlyRequest({
      lat: result.latitude,
      lon: result.longitude,
      nonce: Date.now(),
    });
  }

  const statusMessage = describeMapStatus({
    noFactors,
    cells: {
      status: cells.status,
      count: cells.data?.geohashes.length ?? 0,
      error: cells.error,
    },
    top: {
      status: top.status,
      count: topResults?.length ?? 0,
      error: top.error,
    },
  });

  const factorSummary = `${selection.factors.length} of ${Object.keys(FACTORS).length} factors`;
  const panelOpen = desktop || sheetOpen;

  return (
    <div className={styles.explorer}>
      <aside className={styles.panel} aria-label="Map controls">
        {desktop ? null : (
          <button
            type="button"
            className={styles.sheetToggle}
            aria-expanded={sheetOpen}
            aria-controls={bodyId}
            onClick={() => setSheetOpen((open) => !open)}
          >
            <span>
              Factors &amp; best areas
              <span className={styles.sheetSummary}> · {factorSummary}</span>
            </span>
            <svg
              className={styles.chevron}
              data-open={sheetOpen || undefined}
              viewBox="0 0 24 24"
              aria-hidden="true"
              focusable="false"
            >
              <path d="M6 14l6-6 6 6" />
            </svg>
          </button>
        )}
        <div id={bodyId} className={styles.panelBody} hidden={!panelOpen}>
          <FactorControls selection={selection} onChange={setSelection} />
          <BestAreas
            status={top.status}
            results={topResults}
            error={top.error}
            selectedFactors={selection.factors}
            scope={scope}
            onScopeChange={setScope}
            activeGeohash={activeTop?.geohash ?? null}
            onSelect={selectTop}
            onRetry={top.retry}
          />
        </div>
      </aside>

      <section className={styles.mapArea} aria-label="Map">
        {mapUnavailable ? (
          <div className={styles.unavailable} role="note">
            <p>
              <strong>The map can&rsquo;t be shown in this browser.</strong> It
              needs WebGL. The best-areas list still works and links to each
              area&rsquo;s full breakdown.
            </p>
          </div>
        ) : (
          <MapCanvas
            initialView={initial.view}
            cells={features}
            markers={markers}
            activeMarkerId={activeTop?.geohash ?? null}
            highlightGeohash={highlightGeohash}
            popup={popup}
            flyRequest={flyRequest}
            onViewportChange={(next) => {
              setViewport(next);
              if (next.user) setTopViewport(next);
              else setTopViewport((current) => current ?? next);
            }}
            onCellClick={(cell) => setSelected({ kind: "cell", ...cell })}
            onMarkerClick={(geohash) => {
              const result = topResults?.find((r) => r.geohash === geohash);
              if (result) selectTop(result);
            }}
            onPopupClose={() => setSelected(null)}
            onUnavailable={() => setMapUnavailable(true)}
          />
        )}

        {mapUnavailable ? null : (
          <div className={styles.overlay}>
            <MapLegend range={range} />
            <MapNotices
              loading={cells.status === "loading" && !noFactors}
              noFactors={noFactors}
              empty={
                cells.status === "ready" && cells.data?.geohashes.length === 0
              }
              truncated={
                Boolean(cells.data?.truncated) && cells.status !== "loading"
              }
              count={cells.data?.geohashes.length ?? 0}
              error={
                cells.status === "error"
                  ? (cells.error?.kind ?? "server")
                  : null
              }
              retryAfter={cells.error?.retryAfterSeconds}
              hasData={cells.data !== null}
              onRetry={cells.retry}
            />
          </div>
        )}
      </section>

      <p className="sr-only" role="status">
        {statusMessage}
      </p>
    </div>
  );
}

interface MapNoticesProps {
  loading: boolean;
  noFactors: boolean;
  empty: boolean;
  truncated: boolean;
  count: number;
  error: Parameters<typeof describeError>[0] | null;
  retryAfter?: number;
  hasData: boolean;
  onRetry: () => void;
}

function MapNotices({
  loading,
  noFactors,
  empty,
  truncated,
  count,
  error,
  retryAfter,
  hasData,
  onRetry,
}: MapNoticesProps) {
  const failure = error ? describeError(error) : null;
  return (
    <div className={styles.notices}>
      {loading ? <p className={styles.notice}>Updating scores…</p> : null}
      {noFactors ? (
        <p className={styles.notice}>Select a factor to color the map.</p>
      ) : null}
      {empty && !loading ? (
        <p className={styles.notice}>
          No scored cells in view. Pan or zoom out.
        </p>
      ) : null}
      {truncated ? (
        <p className={styles.notice}>
          Showing {formatCount(count)} cells. Zoom in for more detail.
        </p>
      ) : null}
      {failure ? (
        <div className={`${styles.notice} ${styles.noticeError}`}>
          <p>
            <strong>{failure.title}.</strong>
            {retryAfter ? ` Try again in ${retryAfter} seconds.` : ""}
            {hasData ? " Showing the last scores loaded." : ""}
          </p>
          {failure.retryable ? (
            <button
              type="button"
              className={styles.noticeButton}
              onClick={onRetry}
            >
              Try again
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
