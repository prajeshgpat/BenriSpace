"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
  type ReactNode,
  type Ref,
} from "react";

import { useMapData } from "@/hooks/useMapData";
import { useScoreLookup, type LookupState } from "@/hooks/useScoreLookup";
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
import type { MapTopResult, Suggestion } from "@/lib/api/types";
import { API_BASE_URL } from "@/lib/config";
import { areaTitle, describeMapStatus } from "@/lib/map/presentation";
import {
  explorerHref,
  initialView,
  parseExplorerParams,
  serializeExplorerParams,
  PLACE_ZOOM,
} from "@/lib/map/url";
import { bandLabel, roundScore } from "@/lib/score/presentation";
import { EXAMPLE_ADDRESSES, SITE_TITLE, resultTitle } from "@/lib/site";

import { AddressSearch } from "./AddressSearch";
import { ErrorNotice } from "./ErrorNotice";
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

interface LayoutProps {
  panel: ReactNode;
  map: ReactNode;
  panelRef?: Ref<HTMLElement>;
}

function Layout({ panel, map, panelRef }: LayoutProps) {
  return (
    <div className={styles.workspace}>
      <aside
        ref={panelRef}
        className={styles.panel}
        aria-label="Search and map controls"
        tabIndex={-1}
      >
        {panel}
        <div className={styles.credits}>
          <SiteFooter />
        </div>
      </aside>
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
  const { target, error: urlError } = resolveTarget(params);
  const address = target ? targetLabel(target) : null;
  const placeKey = target ? targetKey(target) : null;

  const { state, retry } = useScoreLookup(target, client);

  const [selection, setSelection] = useState(initial.selection);
  const [scope, setScope] = useState(initial.scope);
  const [viewport, setViewport] = useState<Viewport | null>(null);
  // "This view only" follows what the user is looking at, not the app's own
  // fly-to moves, which would otherwise re-rank the list under their cursor.
  const [topViewport, setTopViewport] = useState<Viewport | null>(null);
  const [picked, setPicked] = useState<Picked | null>(null);
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
  // writing down: the metro overview is what `/` already means.
  const [viewShared, setViewShared] = useState(start.pinned);

  const panelRef = useRef<HTMLElement>(null);
  const searchRef = useRef<HTMLDivElement>(null);
  const flownKey = useRef<string | null>(start.key);

  const { noFactors, cells, top, features, range, topResults } = useMapData({
    client,
    selection,
    scope,
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
    scope,
  });
  // A rejected address in the URL has no state of its own to write back.
  const preserveUrl = target === null && rawAddress !== null;
  useEffect(() => {
    if (preserveUrl) return;
    const next = query ? `/?${query}` : "/";
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
      explorerHref({ target: next, view: urlView, selection, scope }),
    );
  }

  const handleSearch = (next: string) =>
    navigate({ kind: "address", address: next });

  const handleSelectSuggestion = ({ label, latitude, longitude }: Suggestion) =>
    navigate({ kind: "coordinates", lat: latitude, lon: longitude, label });

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
  const highlightGeohash = pickedHere?.geohash ?? null;

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
        />
      </div>

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
              address={state.address}
              score={state.score}
              explanation={state.explanation}
            />
          ) : null}
        </section>
      ) : (
        <Welcome onExample={handleSearch} />
      )}

      <div className={styles.controls}>
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
        pin={target ? point : null}
        flyRequest={flyRequest}
        onViewportChange={(next) => {
          setViewport(next);
          if (next.user) {
            setTopViewport(next);
            setViewShared(true);
          } else setTopViewport((current) => current ?? next);
        }}
        onCellClick={selectCell}
        onMarkerClick={(geohash) => {
          const result = topResults?.find((r) => r.geohash === geohash);
          if (result) selectTop(result);
        }}
        onUnavailable={() => setMapUnavailable(true)}
      />
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

  return <Layout panelRef={panelRef} panel={panel} map={map} />;
}

function Welcome({ onExample }: { onExample: (address: string) => void }) {
  return (
    <section className={styles.welcome} aria-labelledby="welcome-heading">
      <h2 id="welcome-heading" className={styles.welcomeHeading}>
        How convenient is that address?
      </h2>
      <p className={styles.welcomeText}>
        Search for an address in the New York metro area, or click anywhere on
        the map, to see a score out of 100 for groceries, transit, schools,
        trails and more. The map colors show where the factors you pick below
        score best.
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
