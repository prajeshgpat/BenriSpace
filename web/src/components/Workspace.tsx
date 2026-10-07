"use client";

import dynamic from "next/dynamic";
import { useSearchParams } from "next/navigation";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
  type Ref,
  type RefObject,
} from "react";

import { useIsMobile } from "@/hooks/useMediaQuery";
import { useCurrentLocation } from "@/hooks/useCurrentLocation";
import { useCompare } from "@/hooks/useCompare";
import { useLatest } from "@/hooks/useLatest";
import { AskIcon } from "./AskIcon";
import { useMapData } from "@/hooks/useMapData";
import { useReverseGeocode } from "@/hooks/useReverseGeocode";
import { useScoreLookup, type LookupState } from "@/hooks/useScoreLookup";
import { useTheme } from "@/hooks/useTheme";
import {
  ADDRESS_PARAM,
  formatLatLon,
  resolveTarget,
  targetKey,
  targetLabel,
  type LatLon,
  type ScoreTarget,
} from "@/lib/address";
import { createApiClient, type ApiClient } from "@/lib/api/client";
import { isApiError } from "@/lib/api/errors";
import type {
  ChatResult,
  ChatTrip,
  MapTopResult,
  ReachMode,
  Suggestion,
} from "@/lib/api/types";
import { API_BASE_URL, CHAT_STREAM_URL } from "@/lib/config";
import { useAreaScores, useTilesUrl } from "@/hooks/useStaticData";
import { provisionalArea } from "@/lib/static/provisional";
import { round1, subScoresComposite } from "@/lib/scores/matrix";
import {
  OUTSIDE_COVERAGE_MESSAGE,
  YOUR_LOCATION_LABEL,
  isInCoverage,
} from "@/lib/geolocation";
import type { SheetSnap } from "@/lib/sheetSnap";
import { needsReadableAddress } from "@/lib/reverseTarget";
import {
  originBounds,
  pointsAndAreasBounds,
  previewBounds,
  type Preview,
} from "@/lib/map/preview";
import { placeId, type ComparePlace } from "@/lib/compare";
import { areaTitle, describeMapStatus } from "@/lib/map/presentation";
import { priorityQuery } from "@/lib/map/selection";
import {
  explorerHref,
  initialView,
  parseExplorerParams,
  serializeExplorerParams,
  PLACE_ZOOM,
} from "@/lib/map/url";
import { bandLabel, roundScore } from "@/lib/score/presentation";
import { APP_PATH, SITE_TITLE, resultTitle } from "@/lib/site";

import { AddressSearch } from "./AddressSearch";
import { resultKey, TripPlannerPills, TripResults } from "./TripPlanner";
import { effectiveTravel, anchorName, useTripPlanner } from "@/hooks/useTripPlanner";
import { BottomSheet } from "./BottomSheet";
import { PreviewCard } from "./PreviewCard";
import { ImproveCard } from "./ImproveCard";
import { SimilarCard } from "./SimilarCard";
import { ErrorNotice } from "./ErrorNotice";
import { LocateButton } from "./LocateButton";
import { ResultSkeleton } from "./ResultSkeleton";
import { ReachCard } from "./ReachCard";
import { ScoreHeader, ScoreSummary } from "./ScoreResult";
import { SiteFooter } from "./SiteFooter";
import { BestAreas } from "./map/BestAreas";
import { MapErrorBoundary } from "./map/MapErrorBoundary";
import { FactorControls } from "./map/FactorControls";
import type { AreaGeometry } from "@/lib/api/types";
import type { FlyRequest, Viewport } from "./map/MapCanvas";
import { MapLegend } from "./map/MapLegend";
import { TripLegend } from "./map/TripLegend";
import { MapNotices } from "./map/MapNotices";
import styles from "./Workspace.module.css";

// MapLibre is large and WebGL-only: it loads after the shell has hydrated,
// so the search box is usable while the map is still arriving.
const MapCanvas = dynamic(
  () => import("./map/MapCanvas").then((module) => module.MapCanvas),
  { ssr: false, loading: () => <MapPlaceholder /> },
);

// Chat and the compare table are opened on demand, so their code is fetched
// on first use instead of with the first paint.
const ChatPanel = dynamic(
  () => import("./chat/ChatPanel").then((module) => module.ChatPanel),
  { ssr: false },
);
const CompareDrawer = dynamic(
  () => import("./CompareDrawer").then((module) => module.CompareDrawer),
  { ssr: false },
);

const defaultClient = createApiClient({
  baseUrl: API_BASE_URL,
  chatStreamUrl: CHAT_STREAM_URL,
});

function topPlace(r: MapTopResult): ComparePlace {
  return {
    id: placeId(r.latitude, r.longitude),
    label: areaTitle(r),
    neighborhood: r.neighborhood?.trim() || null,
    score: r.score,
    subScores: r.subScores,
    lat: r.latitude,
    lon: r.longitude,
  };
}

/** Zoom for an entry of the best-areas list: a few neighbourhoods across. */
const AREA_ZOOM = 12;
const COORDINATE_DECIMALS = 5;

type Picked = { kind: "top" | "cell"; geohash: string; key: string };

function announcement(state: LookupState): string {
  switch (state.status) {
    case "loading":
      return `Scoring ${state.address}…`;
    case "success": {
      const { compositeScore } = state.score;
      return `${state.address} scores ${roundScore(compositeScore)} out of 100, ${bandLabel(compositeScore)}.`;
    }
    default:
      return "";
  }
}

/** The overall score normalised to the selected factors and weights, as the map colours are. */
function normaliseLookup(
  lookup: LookupState,
  factors: Parameters<typeof subScoresComposite>[1],
  weights: Parameters<typeof subScoresComposite>[2],
): LookupState {
  if (lookup.status !== "success") return lookup;
  const composite = subScoresComposite(lookup.score.subScores, factors, weights);
  if (composite === null) return lookup;
  return { ...lookup, score: { ...lookup.score, compositeScore: round1(composite) } };
}

function roundCoordinate(value: number): number {
  const factor = 10 ** COORDINATE_DECIMALS;
  return Math.round(value * factor) / factor;
}

function MapPlaceholder() {
  return (
    <div className={styles.placeholder} role="status">
      Loading the map…
    </div>
  );
}

/**
 * Visible height of the sheet at each snap, for keeping map controls clear of it. The peek
 * and middle heights follow the content (measured by the sheet) once they are known.
 */
function sheetOffset(snap: SheetSnap, measured: { peek: number; half: number } | null): string {
  if (snap === "peek") {
    return measured
      ? `calc(${measured.peek}px + env(safe-area-inset-bottom, 0px))`
      : "calc(6rem + env(safe-area-inset-bottom, 0px))";
  }
  return snap === "half" && measured ? `calc(${measured.half}px - 0.5rem)` : "calc(50% - 0.5rem)";
}

interface LayoutProps {
  panel: ReactNode;
  map: ReactNode;
  panelRef?: Ref<HTMLElement>;
  snap?: SheetSnap;
  onSnapChange?: (snap: SheetSnap) => void;
  /** The element the collapsed sheet ends under (the search box and the point pills). */
  peekRef?: RefObject<HTMLElement | null>;
  /** The element the middle snap ends under (the score card, or the overlap results). */
  halfRef?: RefObject<HTMLElement | null>;
}

function Layout({
  panel,
  map,
  panelRef,
  snap,
  onSnapChange,
  peekRef,
  halfRef,
}: LayoutProps) {
  const mobile = useIsMobile();
  const [localSnap, setLocalSnap] = useState<SheetSnap>("peek");
  const [measured, setMeasured] = useState<{ peek: number; half: number } | null>(null);
  // On a phone the app is one fixed screen: the page never scrolls under the sheet.
  useEffect(() => {
    if (!mobile) return;
    const root = document.documentElement;
    root.classList.add("workspace-lock");
    return () => root.classList.remove("workspace-lock");
  }, [mobile]);
  const sheetSnap = snap ?? localSnap;
  const content = (
    <>
      {panel}
      <div className={styles.credits}>
        <SiteFooter />
      </div>
    </>
  );
  return (
    <div
      className={styles.workspace}
      style={{ "--sheet-offset": sheetOffset(sheetSnap, measured) } as CSSProperties}
    >
      {mobile ? (
        <BottomSheet
          ref={panelRef}
          snap={sheetSnap}
          onSnapChange={onSnapChange ?? setLocalSnap}
          label="Search and map controls"
          peekRef={peekRef}
          halfRef={halfRef}
          onMeasure={setMeasured}
        >
          {content}
        </BottomSheet>
      ) : (
        <aside
          ref={panelRef}
          className={styles.panel}
          aria-label="Search and map controls"
          tabIndex={-1}
        >
          <div className={styles.panelScroll}>{content}</div>
        </aside>
      )}
      <section className={styles.mapArea} aria-label="Map">
        {map}
      </section>
    </div>
  );
}

/** What the server renders before the URL is known: the search box and an empty map. */
export function WorkspaceFallback() {
  return (
    <Layout
      panel={
        <div className={styles.search}>
          <AddressSearch />
        </div>
      }
      map={<MapPlaceholder />}
    />
  );
}

interface WorkspaceProps {
  client?: ApiClient;
}

export function Workspace({ client = defaultClient }: WorkspaceProps) {
  const params = useSearchParams();
  // The URL is read once for everything but the place being scored; after
  // that the page owns it and only writes to it.
  const [initial] = useState(() => parseExplorerParams(params));
  const rawAddress = params.get(ADDRESS_PARAM);
  const { target: urlTarget, error: urlError } = resolveTarget(params);
  const [picked, setPicked] = useState<Picked | null>(null);
  // Every selection resolves the road-bounded area, like a map click.
  const target: ScoreTarget | null = urlTarget;
  // A clicked point is labelled with coordinates until its street address is looked up.
  // "Your location" keeps its label on screen, but its street address is looked up too so
  // the chat gets a real place instead of the words "Your location".
  const located = target?.kind === "coordinates" && target.label === YOUR_LOCATION_LABEL;
  const reversed = useReverseGeocode(
    needsReadableAddress(target) || located ? { lat: target.lat, lon: target.lon } : null,
    client,
  ).label;
  const readableAddress = located ? null : reversed;
  const address = readableAddress ?? (target ? targetLabel(target) : null);
  const chatAddress = (located ? reversed : null) ?? address;
  const placeKey = target ? targetKey(target) : null;

  const [selection, setSelection] = useState(initial.selection);
  const [viewport, setViewport] = useState<Viewport | null>(null);
  // The best-areas list follows what the user is looking at, not the app's own
  // fly-to moves, which would otherwise re-rank the list under their cursor.
  const [topViewport, setTopViewport] = useState<Viewport | null>(null);
  const [flyRequest, setFlyRequest] = useState<FlyRequest | null>(null);
  // A candidate place shown on the map; it never changes the selected target.
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewArea, setPreviewArea] = useState<{
    key: string;
    geometry: AreaGeometry;
  } | null>(null);
  const [mapUnavailable, setMapUnavailable] = useState(false);
  // The reachable-area polygon from the ReachCard, drawn on the map.
  const [reachGeometry, setReachGeometry] = useState<AreaGeometry | null>(null);
  // "Ask Benri" expands in place where its button sits (side panel and phone
  // sheet alike), with its own scrolling log. `/app?chat=1` (the home page's
  // "Ask Benri") opens it on load; `ask=`
  // pre-fills the search box and the chat context without scoring anything.
  const [chatOpen, setChatOpen] = useState(() => params.get("chat") === "1");
  const [askPrefill, setAskPrefill] = useState(
    () => params.get("ask")?.trim() ?? "",
  );
  // What is in the search box right now, submitted or not.
  const [typedText, setTypedText] = useState(askPrefill);
  const [typedKey, setTypedKey] = useState(placeKey);
  if (typedKey !== placeKey) {
    setTypedKey(placeKey);
    setTypedText("");
    setAskPrefill("");
  }

  const [start] = useState(() => {
    const view = initialView(initial);
    return {
      view,
      key: view && initial.target ? targetKey(initial.target) : null,
      pinned: initial.center !== null || initial.zoom !== null,
    };
  });
  // Until the map moves, or the URL asked for a view, there is no view worth
  // writing down: the metro overview is what `/app` already means.
  const [viewShared, setViewShared] = useState(start.pinned);

  // Phones show the panel as a bottom sheet: collapsed until there is a place
  // to show, and back to collapsed when it is closed.
  const [snap, setSnap] = useState<SheetSnap>(
    chatOpen ? "full" : initial.target ? "half" : "peek",
  );
  const [sheetKey, setSheetKey] = useState(placeKey);
  if (sheetKey !== placeKey) {
    setSheetKey(placeKey);
    // A conversation in progress keeps the sheet where it is.
    if (!chatOpen) setSnap(placeKey ? "half" : "peek");
  }
  // An area picked from the overlap results (see pickOverlap).
  const [overlapPick, setOverlapPick] = useState<{
    lat: number;
    lon: number;
    label: string;
  } | null>(null);
  const [previewPlaceKey, setPreviewPlaceKey] = useState(placeKey);
  if (previewPlaceKey !== placeKey) {
    setPreviewPlaceKey(placeKey);
    if (preview) setPreview(null);
    if (overlapPick) setOverlapPick(null);
  }
  const needSpace = useCallback((kind: "full" | "half") => setSnap(kind), []);
  // Let a click on the map show the map, not the sheet covering it.
  const revealMap = () =>
    setSnap((current) => (current === "full" ? "half" : current));

  const panelRef = useRef<HTMLElement>(null);
  // The search box, notes and point pills: the collapsed sheet ends under them.
  const searchRef = useRef<HTMLDivElement>(null);
  // The score card, or once there is an overlap its results: the middle snap ends under it.
  const halfRef = useRef<HTMLElement | null>(null);
  const flownKey = useRef<string | null>(start.key);

  // The vector-tile grid is opt-in (NEXT_PUBLIC_PMTILES_URL); a tile error
  // switches back to GeoJSON cells for the rest of the visit.
  const [tilesFailed, setTilesFailed] = useState(false);
  const tilesOn = Boolean(useTilesUrl()) && !tilesFailed;
  const areaScores = useAreaScores();
  const { noFactors, cells, top, features, range, topResults, weights, tileCells } =
    useMapData({
      client,
      selection,
      viewport,
      topViewport,
      tiles: tilesOn,
      areaScores,
    });
  // The same selection the map sends, so every card talks about the factors
  // the colours are drawn from.
  const priorities = useMemo(
    () => priorityQuery(selection, weights),
    [selection, weights],
  );

  const { state: lookup, retry } = useScoreLookup(target, client, priorities);
  // The overall score is normalised to the selected factors and weights, with
  // the same arithmetic as the map colours and the best-areas list.
  const state: LookupState = useMemo(
    () => normaliseLookup(lookup, selection.factors, weights),
    [lookup, selection.factors, weights],
  );

  // An area picked from the overlap results: scored on its own, without becoming the
  // searched place.
  const overlapTarget: ScoreTarget | null = useMemo(
    () =>
      overlapPick
        ? {
            kind: "coordinates",
            lat: overlapPick.lat,
            lon: overlapPick.lon,
            label: overlapPick.label,
          }
        : null,
    [overlapPick],
  );
  const { state: pickLookup, retry: retryPick } = useScoreLookup(
    overlapTarget,
    client,
    priorities,
  );
  const pickState: LookupState = useMemo(
    () => normaliseLookup(pickLookup, selection.factors, weights),
    [pickLookup, selection.factors, weights],
  );

  // "+ Point of interest": up to two extra places whose travel-time areas must overlap.
  const tripPlace = useMemo(
    () =>
      state.status === "success"
        ? {
            label: chatAddress ?? state.address,
            lat: state.score.latitude,
            lon: state.score.longitude,
          }
        : null,
    [state, chatAddress],
  );
  // The Travel time row in Factors: the searched place and the points of interest share it.
  const [travel, setTravel] = useState<{ mode: ReachMode; minutes: number } | null>(null);
  const planner = useTripPlanner(client, tripPlace, travel);
  // A box that is armed ("Drop a pin") is waiting for a place: the next tap on the map (a
  // cell or a marker) fills it instead of scoring the tapped place.
  const armedPoi = planner.armedId;
  const poiRows = planner.rows;
  const setPoiPlace = planner.setPlaceFromMap;
  const fillPoiFromMap = useCallback(
    (point: { lat: number; lon: number }): boolean => {
      if (!armedPoi || !poiRows.some((row) => row.id === armedPoi)) return false;
      setPoiPlace(armedPoi, point);
      return true;
    },
    [setPoiPlace, poiRows, armedPoi],
  );
  // When an overlap (or the news that there is none) arrives, bring the places and their
  // travel areas into view.
  const overlapKey =
    planner.data && planner.overlay.pins.length > 1
      ? `${planner.status}:${planner.overlay.pins.length}:${planner.data.combined?.areaSqMi ?? "none"}`
      : null;
  useEffect(() => {
    if (!overlapKey || !planner.data) return;
    const box = pointsAndAreasBounds(planner.overlay.pins, [
      planner.data.combined?.geometry,
      ...planner.overlay.anchors.filter((anchor) => anchor.index === 0).map((anchor) => anchor.geometry),
    ]);
    if (!box) return;
    setFlyRequest({
      lat: (box[1] + box[3]) / 2,
      lon: (box[0] + box[2]) / 2,
      nonce: Date.now(),
      bounds: box,
    });
    // Only when a new overlap arrives, not on every planner render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overlapKey]);
  // Points in a shared link restore the planner once, on load.
  const hydratedPoints = useRef(false);
  useEffect(() => {
    if (hydratedPoints.current) return;
    hydratedPoints.current = true;
    if (initial.points.length > 0) planner.hydrate(initial.points);
  }, [initial.points, planner]);

  // A map click that landed in a known area shows that area's static scores
  // while `/area` loads; the API's answer replaces them.
  const [areaHint, setAreaHint] = useState<{ key: string; areaId: number } | null>(null);
  const provisional = useMemo(
    () =>
      state.status === "loading" &&
      areaScores &&
      areaHint &&
      areaHint.key === placeKey
        ? provisionalArea(areaScores, areaHint.areaId, selection.factors, weights)
        : null,
    [state.status, areaScores, areaHint, placeKey, selection.factors, weights],
  );
  const compare = useCompare();
  // Fetch the chat code once the page is idle, so "Ask Benri" opens at once.
  useEffect(() => {
    const warm = () => void import("./chat/ChatPanel").catch(() => {});
    if (typeof window.requestIdleCallback === "function") {
      const handle = window.requestIdleCallback(warm, { timeout: 4000 });
      return () => window.cancelIdleCallback(handle);
    }
    const handle = window.setTimeout(warm, 2000);
    return () => window.clearTimeout(handle);
  }, []);
  const currentPlace: ComparePlace | null =
    state.status === "success"
      ? {
          id: placeId(state.score.latitude, state.score.longitude),
          label: readableAddress ?? state.address,
          neighborhood: state.score.neighborhood?.trim() || null,
          score: state.score.compositeScore,
          subScores: state.score.subScores,
          lat: state.score.latitude,
          lon: state.score.longitude,
        }
      : null;

  // Stable handlers and props, so the memoized panels below skip the renders
  // that map panning causes.
  const showPreviewRef = useLatest(showPreview);
  const selectTopRef = useLatest(selectTop);
  const currentPlaceRef = useLatest(currentPlace);
  const onPreview = useCallback(
    (next: Preview) => showPreviewRef.current(next),
    [showPreviewRef],
  );
  const onSelectTop = useCallback(
    (result: MapTopResult) => selectTopRef.current(result),
    [selectTopRef],
  );
  const { places: pinned, full: compareFull, toggle: toggleCompare } = compare;
  const topCompare = useMemo(
    () => ({
      isPinned: (r: MapTopResult) =>
        pinned.some((p) => p.id === placeId(r.latitude, r.longitude)),
      full: compareFull,
      // Pinning an area also pins the place that was searched, so the two can be compared.
      onToggle: (r: MapTopResult) =>
        toggleCompare(topPlace(r), currentPlaceRef.current ?? undefined),
    }),
    [pinned, compareFull, toggleCompare, currentPlaceRef],
  );
  const successScore = state.status === "success" ? state.score : null;
  const scoreCoordinates = useMemo(
    () =>
      successScore
        ? { lat: successScore.latitude, lon: successScore.longitude }
        : null,
    [successScore],
  );

  const successAreaId = state.status === "success" ? state.areaId : undefined;
  const similarSource = useMemo(
    () => (successScore ? { subScores: successScore.subScores, areaId: successAreaId } : undefined),
    [successScore, successAreaId],
  );

  const point: LatLon | null =
    target?.kind === "coordinates"
      ? { lat: target.lat, lon: target.lon }
      : state.status === "success"
        ? { lat: state.score.latitude, lon: state.score.longitude }
        : null;
  const pointLat = point?.lat;
  const pointLon = point?.lon;

  const previewLat = preview?.lat;
  const previewLon = preview?.lon;
  const previewKey =
    previewLat === undefined || previewLon === undefined
      ? null
      : `${previewLat},${previewLon}`;
  // The preview's road-bounded polygon is an upgrade over the pin: failures
  // are ignored, and a superseded request is cancelled.
  useEffect(() => {
    if (
      previewKey === null ||
      previewLat === undefined ||
      previewLon === undefined
    ) {
      return;
    }
    const controller = new AbortController();
    client
      .getAreaByCoordinates(
        { lat: previewLat, lon: previewLon },
        { signal: controller.signal },
      )
      .then((result) => {
        if (!controller.signal.aborted) {
          setPreviewArea({ key: previewKey, geometry: result.area.geometry });
        }
      })
      .catch(() => {});
    return () => controller.abort();
  }, [client, previewKey, previewLat, previewLon]);
  const previewGeometry =
    previewArea && previewArea.key === previewKey ? previewArea.geometry : null;

  useEffect(() => {
    if (placeKey === null) {
      flownKey.current = null;
      return;
    }
    if (pointLat === undefined || pointLon === undefined) return;
    if (flownKey.current === placeKey) return;
    flownKey.current = placeKey;
    setFlyRequest({
      lat: pointLat,
      lon: pointLon,
      zoom: PLACE_ZOOM,
      nonce: Date.now(),
    });
  }, [placeKey, pointLat, pointLon]);

  // The result sits above the controls in the panel, and the place may have
  // been picked from far down the list; bring the search and result back.
  useEffect(() => {
    if (placeKey) searchRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [placeKey]);

  // Deliberately runs after every commit: on a direct load of a result URL
  // Next hydrates its own <title> after this component's first effect and
  // would otherwise leave the generic site title in place.
  useEffect(() => {
    document.title = address ? resultTitle(address) : SITE_TITLE;
  });

  const urlView =
    viewShared && viewport
      ? {
          lat: viewport.center.lat,
          lon: viewport.center.lon,
          zoom: viewport.zoom,
        }
      : viewShared
        ? start.view
        : null;
  const query = serializeExplorerParams({
    target,
    view: urlView,
    selection,
    points: planner.urlPoints,
  });
  // A rejected address in the URL has no state of its own to write back.
  const preserveUrl = target === null && rawAddress !== null;
  useEffect(() => {
    if (preserveUrl) return;
    const next = query ? `${APP_PATH}?${query}` : APP_PATH;
    if (window.location.pathname + window.location.search !== next) {
      window.history.replaceState(null, "", next);
    }
  }, [query, preserveUrl]);

  function navigate(next: ScoreTarget | null) {
    setPreview(null);
    if (next && target && targetKey(next) === targetKey(target)) {
      retry();
      planner.retry();
      if (point) {
        setFlyRequest({ ...point, zoom: PLACE_ZOOM, nonce: Date.now() });
      }
      return;
    }
    // The page is static and the lookup runs in the browser, so there is
    // nothing to fetch from the Next.js server. Native pushState keeps
    // useSearchParams in sync without an RSC round trip, and without the
    // router moving focus to the top of the page.
    window.history.pushState(
      null,
      "",
      explorerHref({ target: next, view: urlView, selection, points: planner.urlPoints }),
    );
  }

  // "Score": the typed points of interest are looked up first, then the searched place is
  // scored and the overlap is worked out for all of them.
  const handleSearch = async (next: string) => {
    await planner.resolvePending();
    navigate({ kind: "address", address: next });
  };

  const handleSelectSuggestion = ({ label, latitude, longitude }: Suggestion) =>
    navigate({ kind: "coordinates", lat: latitude, lon: longitude, label });

  async function selectCurrentLocation(point: LatLon): Promise<string | null> {
    if (!isInCoverage(point)) return OUTSIDE_COVERAGE_MESSAGE;
    // Asked first so a place with no data never moves the map. Any other
    // failure is left to the result card, which can retry.
    try {
      await client.getScoreByCoordinates(point);
    } catch (cause) {
      if (isApiError(cause) && cause.kind === "not-found") {
        return OUTSIDE_COVERAGE_MESSAGE;
      }
    }
    navigate({ kind: "coordinates", ...point, label: YOUR_LOCATION_LABEL });
    return null;
  }

  const locator = useCurrentLocation(selectCurrentLocation);
  const { theme } = useTheme();
  const locating = locator.state.status === "locating";
  const locateNoteId = "locate-note";

  function close() {
    setPicked(null);
    navigate(null);
    panelRef.current?.focus({ preventScroll: true });
  }

  function selectCell(cell: { geohash: string; lat: number; lon: number; areaId?: number }) {
    const lat = roundCoordinate(cell.lat);
    const lon = roundCoordinate(cell.lon);
    const next: ScoreTarget = {
      kind: "coordinates",
      lat,
      lon,
      label: formatLatLon({ lat, lon }),
    };
    flownKey.current = targetKey(next);
    setPicked({ kind: "cell", geohash: cell.geohash, key: targetKey(next) });
    setAreaHint(
      cell.areaId === undefined ? null : { key: targetKey(next), areaId: cell.areaId },
    );
    navigate(next);
  }

  // Score an area from the overlap results in the panel, centre the map on it and keep
  // the searched place as it is.
  function pickOverlap({ lat, lon, label }: { lat: number; lon: number; label: string }) {
    setOverlapPick({ lat, lon, label });
    setPreview(null);
    setSnap("half");
    setFlyRequest({ lat, lon, nonce: Date.now() });
  }

  function showPreview(next: Preview) {
    setPreview(next);
    // The sheet would cover the map the preview is meant to show.
    setSnap("peek");
    setFlyRequest({
      lat: next.lat,
      lon: next.lon,
      nonce: Date.now(),
      bounds: previewBounds(next, point),
    });
  }

  function backToOrigin() {
    setPreview(null);
    if (!point) return;
    setFlyRequest({
      ...point,
      nonce: Date.now(),
      bounds: originBounds(
        point,
        state.status === "success" ? (state.area?.geometry ?? null) : null,
      ),
    });
  }

  // Make the previewed spot the selected location; history keeps the old one.
  function promotePreview() {
    if (!preview) return;
    const lat = roundCoordinate(preview.lat);
    const lon = roundCoordinate(preview.lon);
    setPicked(null);
    navigate({
      kind: "coordinates",
      lat,
      lon,
      label: formatLatLon({ lat, lon }),
    });
  }

  function openChat() {
    setChatOpen(true);
    // On a phone the conversation needs the whole sheet.
    setSnap("full");
  }

  // A place the chat found: same map preview the suggestion cards use.
  function showChatResult(result: ChatResult) {
    showPreview({
      lat: result.latitude,
      lon: result.longitude,
      label: result.label,
      subtitle: result.why,
      kind: "best-move",
      summary:
        result.score === undefined
          ? undefined
          : { compositeScore: result.score },
    });
  }

  function scoreChatResult(result: ChatResult) {
    const lat = roundCoordinate(result.latitude);
    const lon = roundCoordinate(result.longitude);
    setPicked(null);
    navigate({ kind: "coordinates", lat, lon, label: result.label });
  }

  function selectTop(result: MapTopResult) {
    if (activeTop?.geohash === result.geohash) {
      close();
      return;
    }
    const next: ScoreTarget = {
      kind: "coordinates",
      lat: result.latitude,
      lon: result.longitude,
      label: areaTitle(result),
    };
    flownKey.current = targetKey(next);
    setPicked({ kind: "top", geohash: result.geohash, key: targetKey(next) });
    setAreaHint(
      result.areaId === undefined ? null : { key: targetKey(next), areaId: result.areaId },
    );
    setFlyRequest({
      lat: result.latitude,
      lon: result.longitude,
      zoom: AREA_ZOOM,
      nonce: Date.now(),
    });
    navigate(next);
  }

  // Once the places' travel areas overlap, the question is about the overlap, not
  // about the one searched place: its score card, summary and suggestions step aside and
  // the best areas in the overlap are the results.
  const entered = planner.hasPlaces;
  // An overlap exists and is drawn.
  const overlapShown = entered && planner.status === "ready";
  // The triangulation's answer (an overlap, or none) is on the map.
  const tripDrawn = entered && (planner.status === "ready" || planner.status === "empty");
  // Removing every point (or losing the overlap) drops the picked area with it.
  if (!overlapShown && overlapPick) setOverlapPick(null);
  const pickOpen = overlapShown && overlapPick !== null;

  const pickedHere = picked?.key === placeKey ? picked : null;
  const activeTop =
    pickedHere?.kind === "top"
      ? (topResults?.find((r) => r.geohash === pickedHere.geohash) ?? null)
      : null;
  // The lookup may upgrade the grid square to a secondary-road polygon, so the
  // rectangle is held back until it settles; it only shows as the fallback
  // when no polygon came back (or the lookup failed).
  // With a place entered the grid-cell rectangle is dropped, so it cannot show through
  // where the area polygon is hidden.
  const highlightGeohash =
    pickedHere && state.status !== "loading" && !entered ? pickedHere.geohash : null;

  const overlapResults = overlapShown ? (planner.data?.results ?? null) : null;
  const markers = useMemo(
    () =>
      overlapResults
        ? overlapResults.map((result, index) => ({
            id: `overlap:${resultKey(result)}`,
            rank: index + 1,
            lat: result.lat,
            lon: result.lon,
            tooltip: `${result.label} \u00b7 ${Math.round(result.score)}`,
            label: `${result.label}, score ${Math.round(result.score)}, rank ${index + 1}. Show details`,
          }))
        : (topResults ?? []).map((result, index) => ({
        id: result.geohash,
        rank: index + 1,
        lat: result.latitude,
        lon: result.longitude,
        tooltip: `${areaTitle(result)} \u00b7 ${Math.round(result.score)}`,
        label: `${areaTitle(result)}, score ${Math.round(result.score)}, rank ${index + 1}. Show details`,
      })),
    [topResults, overlapResults],
  );
  const activeMarkerId =
    overlapShown && overlapPick
      ? `overlap:${resultKey(overlapPick)}`
      : (activeTop?.geohash ?? null);

  const mapStatus = describeMapStatus({
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

  const trip = useMemo<ChatTrip | undefined>(() => {
    if (!entered || !travel) return undefined;
    const places: ChatTrip["places"] = [];
    if (tripPlace) {
      places.push({
        label: tripPlace.label,
        latitude: tripPlace.lat,
        longitude: tripPlace.lon,
        mode: travel.mode,
        minutes: travel.minutes,
      });
    }
    planner.rows.forEach((row, index) => {
      if (row.lat === undefined || row.lon === undefined) return;
      const { mode, minutes } = effectiveTravel(row, travel);
      places.push({
        label: row.label || anchorName(index + 1),
        latitude: row.lat,
        longitude: row.lon,
        mode,
        minutes,
      });
    });
    return {
      places: places.slice(0, 3),
      areas: (planner.status === "ready" ? (planner.data?.results ?? []) : [])
        .slice(0, 5)
        .map((r) => ({ label: r.label, latitude: r.lat, longitude: r.lon, score: Math.round(r.score) })),
      // "No overlap" only once the planner has said so; while it is working nothing is claimed.
      overlap: planner.status !== "empty",
    };
  }, [entered, travel, tripPlace, planner.rows, planner.status, planner.data]);

  const chatProps = {
    client,
    context: {
      ...(target && chatAddress
        ? { address: chatAddress }
        : typedText.trim()
          ? { address: typedText.trim().slice(0, 300) }
          : {}),
      ...(point ? { latitude: point.lat, longitude: point.lon } : {}),
      ...(priorities.factors ? { factors: priorities.factors } : {}),
      ...(priorities.weights ? { weights: priorities.weights } : {}),
      ...(trip ? { trip } : {}),
    },
    place: { key: placeKey, label: target ? chatAddress : null },
    onShowOnMap: showChatResult,
    onScoreArea: scoreChatResult,
    onClose: () => setChatOpen(false),
  };

  const panel = (
    <>
      <div ref={searchRef} className={styles.search}>
        <AddressSearch
          initialValue={rawAddress ?? address ?? askPrefill}
          onTextChange={setTypedText}
          initialError={urlError}
          onSearch={handleSearch}
          onSelectSuggestion={handleSelectSuggestion}
          suggestClient={client}
          endAdornment={
            <LocateButton
              variant="field"
              locating={locating}
              disabled={locator.unsupported !== null}
              describedBy={locator.unsupported ? locateNoteId : undefined}
              onClick={locator.locate}
            />
          }
        />
        <div className={styles.locate}>
          {locator.unsupported ? (
            <p id={locateNoteId} className={styles.locateNote}>
              {locator.unsupported}
            </p>
          ) : null}
          <div aria-live="assertive" aria-atomic="true">
            {locator.state.status === "error" ? (
              <p className={styles.locateError}>{locator.state.message}</p>
            ) : null}
          </div>
        </div>
        <TripPlannerPills
          planner={planner}
          client={client}
          onNeedSpace={needSpace}
        />
      </div>

      {/* Below the collapsed sheet: working-out, errors and the best areas in the overlap. A
          result is previewed on the map like a similar area; it only becomes the searched
          place when promoted from the preview. */}
      {pickOpen && overlapPick ? (
        <section
          ref={halfRef}
          className={styles.result}
          data-state={pickState.status}
          aria-label="Area in the overlap"
        >
          <button type="button" className={styles.close} onClick={() => setOverlapPick(null)}>
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
            <span className="sr-only">Close area in the overlap</span>
          </button>
          <div className={styles.headerSlot}>
            {pickState.status === "loading" ? <ResultSkeleton /> : null}
            {pickState.status === "error" ? (
              <ErrorNotice
                address={overlapPick.label}
                error={pickState.error}
                onRetry={retryPick}
              />
            ) : null}
            {pickState.status === "success" ? (
              <ScoreHeader
                address={overlapPick.label}
                score={pickState.score}
                area={pickState.area}
                hideCopyLink
              />
            ) : null}
          </div>
        </section>
      ) : null}
      <TripResults
        planner={planner}
        sectionRef={overlapShown && !pickOpen ? halfRef : undefined}
        selectedKey={pickOpen && overlapPick ? resultKey(overlapPick) : null}
        onSelectResult={pickOverlap}
        onNeedSpace={needSpace}
      />

      <p className="sr-only" role="status">
        {locating ? "Finding your location\u2026" : ""}
      </p>

      <p className="sr-only" role="status">
        {announcement(state)}
      </p>

      <p className="sr-only" role="status">
        {pickOpen ? announcement(pickState) : ""}
      </p>

      {chatOpen ? <ChatPanel {...chatProps} /> : null}

      {target && !overlapShown ? (
        <section
          ref={halfRef}
          className={styles.result}
          data-state={state.status}
          aria-label="Selected location"
        >
          <button type="button" className={styles.close} onClick={close}>
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
            <span className="sr-only">Close result</span>
          </button>
          {/* Fixed-height slot: loading, success and error share it, so the
              filters below never move when a result arrives. */}
          <div className={styles.headerSlot}>
            {state.status === "loading" && !provisional ? <ResultSkeleton /> : null}
            {state.status === "loading" && provisional ? (
              <div aria-busy="true" data-testid="provisional-score">
                <ScoreHeader
                  address={readableAddress ?? state.address}
                  score={provisional}
                />
              </div>
            ) : null}
            {state.status === "error" ? (
              <ErrorNotice
                address={state.address}
                error={state.error}
                onRetry={retry}
              />
            ) : null}
            {state.status === "success" ? (
              <ScoreHeader
                address={readableAddress ?? state.address}
                score={state.score}
                area={state.area}
                compare={
                  currentPlace
                    ? {
                        pinned: compare.places.some(
                          (p) => p.id === currentPlace.id,
                        ),
                        full: compare.full,
                        onToggle: () => compare.toggle(currentPlace),
                      }
                    : undefined
                }
              />
            ) : null}
          </div>
        </section>
      ) : null}

      {chatOpen ? null : (
        <button type="button" className={styles.ask} onClick={openChat}>
          <AskIcon className={styles.askIcon} />
          Ask Benri
        </button>
      )}

      <div className={styles.controls}>
        <FactorControls
          selection={selection}
          onChange={setSelection}
          scores={
            pickOpen && pickState.status === "success"
              ? pickState.score.subScores
              : state.status === "success"
                ? state.score.subScores
                : (provisional?.subScores ?? null)
          }
        >
          {/* Always mounted, so a switched-on travel area survives a change of place. */}
          <ReachCard
            coordinates={
              state.status === "success"
                ? { lat: state.score.latitude, lon: state.score.longitude }
                : null
            }
            travelMode={state.status === "success" ? state.score.travelMode : null}
            client={client}
            onReach={setReachGeometry}
            suspended={tripDrawn}
            onTravelChange={setTravel}
          />
        </FactorControls>
        {state.status === "success" && !overlapShown ? (
          <>
            <ScoreSummary
              score={state.score}
              explanation={state.explanation}
              client={client}
              target={readableAddress ?? state.address}
            />
            <ImproveCard
              coordinates={scoreCoordinates ?? { lat: state.score.latitude, lon: state.score.longitude }}
              client={client}
              priorities={priorities}
              onPreview={onPreview}
            />
            <SimilarCard
              coordinates={scoreCoordinates ?? { lat: state.score.latitude, lon: state.score.longitude }}
              client={client}
              priorities={priorities}
              source={similarSource}
              onPreview={onPreview}
            />
          </>
        ) : null}
        {overlapShown ? null : (
          <BestAreas
            status={top.status}
            results={topResults}
            error={top.error}
            selectedFactors={selection.factors}
            activeGeohash={activeTop?.geohash ?? null}
            onSelect={onSelectTop}
            onRetry={top.retry}
            compare={topCompare}
            feedbackClient={client}
          />
        )}
      </div>
      <p className="sr-only" role="status">
        {mapStatus}
      </p>
      {compare.places.length > 0 ? (
        <CompareDrawer
          places={compare.places}
          onRemove={compare.remove}
          onClear={compare.clear}
        />
      ) : null}
    </>
  );

  const map = mapUnavailable ? (
    <div className={styles.unavailable} role="note">
      <p>
        <strong>The map can&rsquo;t be shown in this browser.</strong> It needs
        WebGL. Address search and the best-areas list still work and show each
        place&rsquo;s full score.
      </p>
    </div>
  ) : (
    <>
      <MapErrorBoundary>
        <MapCanvas
          initialView={start.view}
          cells={features}
          markers={markers}
          activeMarkerId={activeMarkerId}
          highlightGeohash={highlightGeohash}
          tileCells={tilesOn ? tileCells : null}
          onTilesFailed={() => setTilesFailed(true)}
          areaGeometry={
            pickOpen && pickState.status === "success"
              ? (pickState.area?.geometry ?? null)
              : state.status === "success" && !overlapShown
                ? (state.area?.geometry ?? null)
                : null
          }
          theme={theme}
          previewAreaGeometry={preview ? previewGeometry : null}
          reachGeometry={reachGeometry}
          triangulation={entered ? planner.overlay : null}
          previewPin={preview ? { lat: preview.lat, lon: preview.lon } : null}
          pin={target ? point : null}
          flyRequest={flyRequest}
          onViewportChange={(next) => {
            setViewport(next);
            if (next.user) {
              setTopViewport(next);
              setViewShared(true);
            } else setTopViewport((current) => current ?? next);
          }}
          onCellClick={(cell) => {
            if (fillPoiFromMap({ lat: cell.lat, lon: cell.lon })) return;
            revealMap();
            selectCell(cell);
          }}
          onMarkerClick={(id) => {
            const overlap = overlapResults?.find((r) => `overlap:${resultKey(r)}` === id);
            if (overlap) {
              if (fillPoiFromMap({ lat: overlap.lat, lon: overlap.lon })) return;
              pickOverlap(overlap);
              return;
            }
            const geohash = id;
            const result = topResults?.find((r) => r.geohash === geohash);
            if (result && fillPoiFromMap({ lat: result.latitude, lon: result.longitude })) return;
            revealMap();
            if (result) selectTop(result);
          }}
          onUnavailable={() => setMapUnavailable(true)}
        />
      </MapErrorBoundary>
      {preview ? (
        <PreviewCard
          preview={preview}
          originLabel={address}
          onBack={backToOrigin}
          onPromote={promotePreview}
          onClose={() => setPreview(null)}
        />
      ) : null}
      {locator.unsupported ? null : (
        <div className={styles.mapLocate}>
          <LocateButton
            variant="map"
            locating={locating}
            onClick={locator.locate}
          />
        </div>
      )}
      <div className={styles.overlay}>
        <MapLegend range={range} />
        {entered ? <TripLegend overlay={planner.overlay} status={planner.status} /> : null}
        <MapNotices
          loading={cells.status === "loading" && !noFactors}
          noFactors={noFactors}
          empty={cells.status === "ready" && cells.data?.geohashes.length === 0}
          truncated={
            Boolean(cells.data?.truncated) && cells.status !== "loading"
          }
          count={cells.data?.geohashes.length ?? 0}
          error={
            cells.status === "error" ? (cells.error?.kind ?? "server") : null
          }
          retryAfter={cells.error?.retryAfterSeconds}
          hasData={cells.data !== null}
          onRetry={cells.retry}
        />
      </div>
    </>
  );

  return (
    <Layout
      panelRef={panelRef}
      peekRef={searchRef}
      halfRef={halfRef}
      panel={panel}
      map={map}
      snap={snap}
      onSnapChange={setSnap}
    />
  );
}
