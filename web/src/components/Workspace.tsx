"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type MouseEvent,
  type ReactNode,
  type Ref,
} from "react";

import { useIsMobile } from "@/hooks/useMediaQuery";
import { useCurrentLocation } from "@/hooks/useCurrentLocation";
import { useMapData } from "@/hooks/useMapData";
import { useReverseGeocode } from "@/hooks/useReverseGeocode";
import { useScoreLookup, type LookupState } from "@/hooks/useScoreLookup";
import { useTheme } from "@/hooks/useTheme";
import {
  ADDRESS_PARAM,
  formatLatLon,
  resolveTarget,
  resultHref,
  targetKey,
  targetLabel,
  type LatLon,
  type ScoreTarget,
} from "@/lib/address";
import { createApiClient, type ApiClient } from "@/lib/api/client";
import { isApiError } from "@/lib/api/errors";
import type { MapTopResult, Suggestion } from "@/lib/api/types";
import { API_BASE_URL } from "@/lib/config";
import {
  OUTSIDE_COVERAGE_MESSAGE,
  YOUR_LOCATION_LABEL,
  isInCoverage,
} from "@/lib/geolocation";
import type { SheetSnap } from "@/lib/sheetSnap";
import { needsReadableAddress } from "@/lib/reverseTarget";
import { areaTitle, describeMapStatus } from "@/lib/map/presentation";
import {
  explorerHref,
  initialView,
  parseExplorerParams,
  serializeExplorerParams,
  PLACE_ZOOM,
} from "@/lib/map/url";
import { bandLabel, roundScore } from "@/lib/score/presentation";
import { APP_PATH, EXAMPLE_ADDRESSES, SITE_TITLE, resultTitle } from "@/lib/site";

import { AddressSearch } from "./AddressSearch";
import { BottomSheet } from "./BottomSheet";
import { ImproveCard } from "./ImproveCard";
import { ErrorNotice } from "./ErrorNotice";
import { LocateButton } from "./LocateButton";
import { ResultSkeleton } from "./ResultSkeleton";
import { ScoreResult } from "./ScoreResult";
import { SiteFooter } from "./SiteFooter";
import { BestAreas } from "./map/BestAreas";
import { FactorControls } from "./map/FactorControls";
import type { FlyRequest, Viewport } from "./map/MapCanvas";
import { MapLegend } from "./map/MapLegend";
import { MapNotices } from "./map/MapNotices";
import styles from "./Workspace.module.css";

// MapLibre is large and WebGL-only: it loads after the shell has hydrated,
// so the search box is usable while the map is still arriving.
const MapCanvas = dynamic(
  () => import("./map/MapCanvas").then((module) => module.MapCanvas),
  { ssr: false, loading: () => <MapPlaceholder /> },
);

const defaultClient = createApiClient({ baseUrl: API_BASE_URL });

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

function isModifiedClick(event: MouseEvent): boolean {
  return (
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  );
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

/** Visible height of the sheet at each snap, for keeping map controls clear of it. */
const SHEET_OFFSET: Record<SheetSnap, string> = {
  peek: "calc(6rem + env(safe-area-inset-bottom, 0px))",
  half: "calc(50% - 0.5rem)",
  full: "calc(50% - 0.5rem)",
};

interface LayoutProps {
  panel: ReactNode;
  map: ReactNode;
  panelRef?: Ref<HTMLElement>;
  snap?: SheetSnap;
  onSnapChange?: (snap: SheetSnap) => void;
}

function Layout({ panel, map, panelRef, snap, onSnapChange }: LayoutProps) {
  const mobile = useIsMobile();
  const [localSnap, setLocalSnap] = useState<SheetSnap>("peek");
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
      style={{ "--sheet-offset": SHEET_OFFSET[sheetSnap] } as CSSProperties}
    >
      {mobile ? (
        <BottomSheet
          ref={panelRef}
          snap={sheetSnap}
          onSnapChange={onSnapChange ?? setLocalSnap}
          label="Search and map controls"
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
          {content}
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
  // The URL only carries lat/lon, so a best-areas pick is re-marked as
  // cell-based here; a shared link or reload resolves the area instead.
  const target: ScoreTarget | null =
    urlTarget?.kind === "coordinates" &&
    picked?.kind === "top" &&
    picked.key === targetKey(urlTarget)
      ? { ...urlTarget, precision: "cell" }
      : urlTarget;
  // A clicked point is labelled with coordinates until its street address is looked up.
  const readableAddress = useReverseGeocode(
    needsReadableAddress(target) ? { lat: target.lat, lon: target.lon } : null,
    client,
  ).label;
  const address = readableAddress ?? (target ? targetLabel(target) : null);
  const placeKey = target ? targetKey(target) : null;

  const { state, retry } = useScoreLookup(target, client);

  const [selection, setSelection] = useState(initial.selection);
  const [viewport, setViewport] = useState<Viewport | null>(null);
  // The best-areas list follows what the user is looking at, not the app's own
  // fly-to moves, which would otherwise re-rank the list under their cursor.
  const [topViewport, setTopViewport] = useState<Viewport | null>(null);
  const [flyRequest, setFlyRequest] = useState<FlyRequest | null>(null);
  const [mapUnavailable, setMapUnavailable] = useState(false);

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

  const mobile = useIsMobile();
  // Phones show the panel as a bottom sheet: collapsed until there is a place
  // to show, and back to collapsed when it is closed.
  const [snap, setSnap] = useState<SheetSnap>(
    initial.target ? "half" : "peek",
  );
  const [sheetKey, setSheetKey] = useState(placeKey);
  if (sheetKey !== placeKey) {
    setSheetKey(placeKey);
    setSnap(placeKey ? "half" : "peek");
  }
  // Let a click on the map show the map, not the sheet covering it.
  const revealMap = () => setSnap((current) => (current === "full" ? "half" : current));

  const panelRef = useRef<HTMLElement>(null);
  const searchRef = useRef<HTMLDivElement>(null);
  const flownKey = useRef<string | null>(start.key);

  const { noFactors, cells, top, features, range, topResults } = useMapData({
    client,
    selection,
    viewport,
    topViewport,
  });

  const point: LatLon | null =
    target?.kind === "coordinates"
      ? { lat: target.lat, lon: target.lon }
      : state.status === "success"
        ? { lat: state.score.latitude, lon: state.score.longitude }
        : null;
  const pointLat = point?.lat;
  const pointLon = point?.lon;

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
    if (next && target && targetKey(next) === targetKey(target)) {
      retry();
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
      explorerHref({ target: next, view: urlView, selection }),
    );
  }

  const handleSearch = (next: string) =>
    navigate({ kind: "address", address: next });

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

  function selectCell(cell: { geohash: string; lat: number; lon: number }) {
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
    navigate(next);
  }

  // Fly the map to a suggested spot and pin it as the selected location.
  function focusPoint(lat: number, lon: number) {
    const next: ScoreTarget = {
      kind: "coordinates",
      lat: roundCoordinate(lat),
      lon: roundCoordinate(lon),
      label: formatLatLon({ lat, lon }),
    };
    flownKey.current = targetKey(next);
    setPicked(null);
    setFlyRequest({ lat, lon, zoom: PLACE_ZOOM, nonce: Date.now() });
    navigate(next);
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
      // The ranked square is the unit the list is scored on; stay cell-based.
      precision: "cell",
    };
    flownKey.current = targetKey(next);
    setPicked({ kind: "top", geohash: result.geohash, key: targetKey(next) });
    setFlyRequest({
      lat: result.latitude,
      lon: result.longitude,
      zoom: AREA_ZOOM,
      nonce: Date.now(),
    });
    navigate(next);
  }

  const pickedHere = picked?.key === placeKey ? picked : null;
  const activeTop =
    pickedHere?.kind === "top"
      ? (topResults?.find((r) => r.geohash === pickedHere.geohash) ?? null)
      : null;
  // The lookup may upgrade the grid square to a secondary-road polygon, so the
  // rectangle is held back until it settles; it only shows as the fallback
  // when no polygon came back (or the lookup failed).
  const highlightGeohash =
    pickedHere && state.status !== "loading" ? pickedHere.geohash : null;

  const markers = useMemo(
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

  const panel = (
    <>
      <div ref={searchRef} className={styles.search}>
        <AddressSearch
          initialValue={rawAddress ?? (address ?? "")}
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
      </div>

      <p className="sr-only" role="status">
        {locating ? "Finding your location\u2026" : ""}
      </p>

      <p className="sr-only" role="status">
        {announcement(state)}
      </p>

      {target ? (
        <section
          className={styles.result}
          data-state={state.status}
          aria-label="Selected location"
        >
          <button type="button" className={styles.close} onClick={close}>
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
            Close result
          </button>
          {state.status === "loading" ? <ResultSkeleton /> : null}
          {state.status === "error" ? (
            <ErrorNotice
              address={state.address}
              error={state.error}
              onRetry={retry}
            />
          ) : null}
          {state.status === "success" ? (
            <ScoreResult
              address={readableAddress ?? state.address}
              readableAddress={readableAddress}
              score={state.score}
              area={state.area}
              explanation={state.explanation}
            />
          ) : null}
          {state.status === "success" ? (
            <ImproveCard
              coordinates={{ lat: state.score.latitude, lon: state.score.longitude }}
              client={client}
              onFocusPoint={focusPoint}
            />
          ) : null}
        </section>
      ) : mobile && snap === "peek" ? null : (
        <Welcome onExample={handleSearch} />
      )}

      <div className={styles.controls}>
        <FactorControls selection={selection} onChange={setSelection} />
        <BestAreas
          status={top.status}
          results={topResults}
          error={top.error}
          selectedFactors={selection.factors}
          activeGeohash={activeTop?.geohash ?? null}
          onSelect={selectTop}
          onRetry={top.retry}
        />
      </div>
      <p className="sr-only" role="status">
        {mapStatus}
      </p>
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
      <MapCanvas
        initialView={start.view}
        cells={features}
        markers={markers}
        activeMarkerId={activeTop?.geohash ?? null}
        highlightGeohash={highlightGeohash}
        areaGeometry={state.status === "success" ? (state.area?.geometry ?? null) : null}
        theme={theme}
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
          revealMap();
          selectCell(cell);
        }}
        onMarkerClick={(geohash) => {
          revealMap();
          const result = topResults?.find((r) => r.geohash === geohash);
          if (result) selectTop(result);
        }}
        onUnavailable={() => setMapUnavailable(true)}
      />
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
      panel={panel}
      map={map}
      snap={snap}
      onSnapChange={setSnap}
    />
  );
}

function Welcome({ onExample }: { onExample: (address: string) => void }) {
  return (
    <section className={styles.welcome} aria-label="Get started">
      <p className={styles.welcomeText}>
        Search an address or click the map to see its score.{" "}
        <Link href="/" prefetch={false}>
          How scores work
        </Link>
      </p>
      <p className={styles.examples}>
        <span className={styles.examplesLabel}>Try</span>
        {EXAMPLE_ADDRESSES.map((example) => (
          <Link
            key={example}
            className={styles.example}
            href={resultHref(example)}
            prefetch={false}
            onClick={(event) => {
              if (isModifiedClick(event)) return;
              event.preventDefault();
              onExample(example);
            }}
          >
            {example}
          </Link>
        ))}
      </p>
    </section>
  );
}
