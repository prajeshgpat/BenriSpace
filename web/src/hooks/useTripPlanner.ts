"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { formatLatLon } from "@/lib/address";
import type { ApiClient } from "@/lib/api/client";
import type {
  AreaGeometry,
  Isochrone,
  ReachMode,
  Suggestion,
  TriangulateAnchor,
} from "@/lib/api/types";
import type { UrlPoint } from "@/lib/map/url";

/** Your place plus two points of interest. */
export const MAX_TRIP_ROWS = 3;
/** Wait for the last edit before asking the server. */
export const TRIANGULATE_DEBOUNCE_MS = 400;
/** Overlap results closer than this are one place to the reader. */
export const MIN_RESULT_SEPARATION_MI = 0.25;
export const MAX_TRIP_RESULTS = 5;
export const NOT_FOUND_MESSAGE = "Couldn't find that address. Pick one from the list.";

export interface TripRow {
  id: string;
  label: string;
  lat?: number;
  lon?: number;
  mode: ReachMode;
  minutes: number;
  /** Set when typed text could not be resolved to a place. */
  error: string | null;
}

/** The place being scored, from which row 0 is created. */
export interface TripPlace {
  label: string;
  lat: number;
  lon: number;
  /** How people here usually travel: "walk" means dense. */
  travelMode?: "walk" | "drive" | null;
}

export interface TripResult {
  lat: number;
  lon: number;
  /** The API's composite score, not the user's factor-normalised one. */
  score: number;
  label: string;
}

export interface TripData {
  results: TripResult[];
  isochrones: Isochrone[];
  combined: Isochrone | null;
  /** Some area is a straight-line estimate rather than road routing. */
  estimate: boolean;
}

export type TripStatus = "idle" | "loading" | "ready" | "empty" | "error";

export interface TripOverlayAnchor {
  /** 0 = your place, 1 and 2 = points of interest. */
  index: number;
  label: string;
  lat: number;
  lon: number;
  geometry: AreaGeometry | null;
}

/** What the map draws for the planner. */
export interface TripOverlay {
  anchors: TripOverlayAnchor[];
  combined: AreaGeometry | null;
  /** Numbered pins, in the anchor colours. */
  pins: { index: number; label: string; lat: number; lon: number }[];
}

type ClientSubset = Pick<ApiClient, "triangulate" | "reverseGeocode" | "suggestAddresses">;

/** Default minutes when a mode is picked (also the starting value for a new row). */
export const DEFAULT_MINUTES: Record<ReachMode, number> = {
  walk: 10,
  transit: 20,
  drive: 15,
};

export function defaultTravelFor(dense: boolean): { mode: ReachMode; minutes: number } {
  return dense ? { mode: "transit", minutes: 20 } : { mode: "drive", minutes: 15 };
}

const EARTH_RADIUS_MI = 3958.8;

export function distanceMi(
  a: { lat: number; lon: number },
  b: { lat: number; lon: number },
): number {
  const rad = Math.PI / 180;
  const dLat = (b.lat - a.lat) * rad;
  const dLon = (b.lon - a.lon) * rad;
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_MI * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** Best first, at most `MAX_TRIP_RESULTS`, none within 0.25 mi of a better one. */
export function pickSpreadResults<T extends { lat: number; lon: number; score: number }>(
  results: readonly T[],
): T[] {
  const picked: T[] = [];
  for (const candidate of [...results].sort((a, b) => b.score - a.score)) {
    if (picked.every((p) => distanceMi(p, candidate) >= MIN_RESULT_SEPARATION_MI)) {
      picked.push(candidate);
      if (picked.length === MAX_TRIP_RESULTS) break;
    }
  }
  return picked;
}

const COORDINATE_TEXT = /^\s*-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?\s*$/;

function hasCoordinates(row: TripRow): row is TripRow & { lat: number; lon: number } {
  return row.lat !== undefined && row.lon !== undefined;
}

function anchorName(index: number): string {
  return index === 0 ? "Your place" : `Point ${index}`;
}

type Settled =
  | { key: string; status: "ready" | "empty"; data: TripData }
  | { key: string; status: "error" };

export interface TripPlannerState {
  rows: TripRow[];
  /** Any row exists: the single-place travel area should step aside. */
  active: boolean;
  /** The "+ Point of interest" control is usable. */
  canAdd: boolean;
  /** Id of the row added by the last `add`, so the UI can focus it. */
  lastAddedId: string | null;
  status: TripStatus;
  data: TripData | null;
  overlay: TripOverlay;
  /** Rows with coordinates, for the shared URL. */
  urlPoints: UrlPoint[];
  add: () => void;
  /** Removing row 0 or the last point of interest removes the whole planner. */
  remove: (id: string) => void;
  setTravel: (id: string, travel: { mode: ReachMode; minutes: number }) => void;
  /** A suggestion was picked for this row. */
  selectSuggestion: (id: string, suggestion: Suggestion) => void;
  /** Typed text was submitted without picking a suggestion. */
  submitText: (id: string, text: string) => void;
  /** The row's x button: forget its place. */
  clearPlace: (id: string) => void;
  /** Rebuild the planner from URL points; labels are looked up afterwards. */
  hydrate: (points: readonly UrlPoint[]) => void;
  retry: () => void;
}

/**
 * The state behind the "+ Point of interest" planner: up to three anchors
 * (row 0 is a frozen copy of the searched place), a debounced call to
 * `POST /triangulate`, and the spread-out list of best areas in the overlap.
 */
export function useTripPlanner(
  client: ClientSubset,
  place: TripPlace | null,
): TripPlannerState {
  const [rows, setRows] = useState<TripRow[]>([]);
  const [lastAddedId, setLastAddedId] = useState<string | null>(null);
  const [settled, setSettled] = useState<Settled | null>(null);
  const [nonce, setNonce] = useState(0);
  const counter = useRef(0);
  const resolving = useRef(new Map<string, number>());
  const labels = useRef(new Map<string, string | null>());
  const clientRef = useRef(client);
  useEffect(() => {
    clientRef.current = client;
  });

  const nextId = () => `trip-${(counter.current += 1)}`;

  const patchRow = useCallback((id: string, patch: Partial<TripRow>) => {
    setRows((current) => current.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  }, []);

  const add = useCallback(() => {
    if (rows.length >= MAX_TRIP_ROWS) return;
    // New rows follow the searched place's density, even once row 0 exists.
    const travel = defaultTravelFor(place?.travelMode === "walk");
    const added: TripRow[] = [];
    if (rows.length === 0) {
      added.push({
        id: nextId(),
        label: place?.label ?? "",
        lat: place?.lat,
        lon: place?.lon,
        ...travel,
        error: null,
      });
    }
    const point: TripRow = { id: nextId(), label: "", ...travel, error: null };
    added.push(point);
    setLastAddedId(point.id);
    setRows([...rows, ...added]);
  }, [rows, place]);

  const remove = useCallback((id: string) => {
    setRows((current) => {
      const index = current.findIndex((r) => r.id === id);
      if (index === -1) return current;
      if (index === 0 || current.length <= 2) return [];
      return current.filter((r) => r.id !== id);
    });
  }, []);

  const setTravel = useCallback(
    (id: string, travel: { mode: ReachMode; minutes: number }) => patchRow(id, travel),
    [patchRow],
  );

  const selectSuggestion = useCallback(
    (id: string, suggestion: Suggestion) => {
      resolving.current.delete(id);
      patchRow(id, {
        label: suggestion.label,
        lat: suggestion.latitude,
        lon: suggestion.longitude,
        error: null,
      });
    },
    [patchRow],
  );

  const clearPlace = useCallback(
    (id: string) => {
      resolving.current.delete(id);
      patchRow(id, { label: "", lat: undefined, lon: undefined, error: null });
    },
    [patchRow],
  );

  const submitText = useCallback(
    (id: string, text: string) => {
      const query = text.trim();
      if (query === "") return;
      const token = (resolving.current.get(id) ?? 0) + 1;
      resolving.current.set(id, token);
      clientRef.current
        .suggestAddresses(query, { limit: 1 })
        .then((found) => {
          if (resolving.current.get(id) !== token) return;
          const first = found[0];
          if (!first) {
            patchRow(id, { error: NOT_FOUND_MESSAGE });
            return;
          }
          patchRow(id, {
            label: first.label,
            lat: first.latitude,
            lon: first.longitude,
            error: null,
          });
        })
        .catch(() => {
          if (resolving.current.get(id) !== token) return;
          patchRow(id, { error: NOT_FOUND_MESSAGE });
        });
    },
    [patchRow],
  );

  const hydrate = useCallback(
    (points: readonly UrlPoint[]) => {
      const restored: TripRow[] = points.slice(0, MAX_TRIP_ROWS).map((p) => ({
        id: nextId(),
        label: formatLatLon(p),
        lat: p.lat,
        lon: p.lon,
        mode: p.mode,
        minutes: p.minutes,
        error: null,
      }));
      setRows(restored.length >= 2 ? restored : []);
      if (restored.length < 2) return;
      for (const row of restored) {
        clientRef.current
          .reverseGeocode({ lat: row.lat as number, lon: row.lon as number })
          .then(({ label }) => {
            if (label) {
              setRows((current) =>
                current.map((r) =>
                  r.id === row.id && r.label === formatLatLon(r as { lat: number; lon: number })
                    ? { ...r, label }
                    : r,
                ),
              );
            }
          })
          .catch(() => {});
      }
    },
    // nextId only touches a ref.
    [],
  );

  const anchors = useMemo<TriangulateAnchor[]>(
    () =>
      rows.flatMap((row, index) =>
        hasCoordinates(row)
          ? [
              {
                label: row.label || anchorName(index),
                lat: row.lat,
                lon: row.lon,
                mode: row.mode,
                minutes: row.minutes,
              },
            ]
          : [],
      ),
    [rows],
  );
  const anchorKey = anchors.length < 2 ? null : `${JSON.stringify(anchors)}#${nonce}`;

  useEffect(() => {
    if (anchorKey === null) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      clientRef.current
        .triangulate(anchors, { signal: controller.signal })
        .then((response) => {
          if (controller.signal.aborted) return;
          const spread = pickSpreadResults(response.results).map<TripResult>((r) => ({
            lat: r.lat,
            lon: r.lon,
            score: r.score,
            label: COORDINATE_TEXT.test(r.address) || r.address === "" ? formatLatLon(r) : r.address,
          }));
          const empty =
            response.combined === null ||
            response.combined.cellCount === 0 ||
            spread.length === 0;
          const data: TripData = {
            results: spread,
            isochrones: response.isochrones,
            combined: response.combined,
            estimate: [...response.isochrones, response.combined].some(
              (iso) => iso?.method === "estimate",
            ),
          };
          setSettled({ key: anchorKey, status: empty ? "empty" : "ready", data });

          for (const result of spread) {
            const cacheKey = `${result.lat.toFixed(4)},${result.lon.toFixed(4)}`;
            const apply = (label: string | null) => {
              if (!label) return;
              setSettled((current) =>
                current && current.key === anchorKey && current.status !== "error"
                  ? {
                      ...current,
                      data: {
                        ...current.data,
                        results: current.data.results.map((r) =>
                          r.lat === result.lat && r.lon === result.lon ? { ...r, label } : r,
                        ),
                      },
                    }
                  : current,
              );
            };
            if (labels.current.has(cacheKey)) {
              apply(labels.current.get(cacheKey) ?? null);
              continue;
            }
            clientRef.current
              .reverseGeocode(result, { signal: controller.signal })
              .then(({ label }) => {
                labels.current.set(cacheKey, label);
                if (!controller.signal.aborted) apply(label);
              })
              .catch(() => {});
          }
        })
        .catch(() => {
          if (controller.signal.aborted) return;
          setSettled({ key: anchorKey, status: "error" });
        });
    }, TRIANGULATE_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
    // `anchors` is captured by `anchorKey`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anchorKey]);

  const status: TripStatus =
    anchorKey === null ? "idle" : settled?.key === anchorKey ? settled.status : "loading";
  const data = status === "ready" || status === "empty" ? (settled as { data: TripData }).data : null;

  const overlay = useMemo<TripOverlay>(() => {
    const placed = rows.flatMap((row, index) =>
      hasCoordinates(row) ? [{ row, index }] : [],
    );
    const iso = data?.isochrones ?? [];
    return {
      anchors: placed.map(({ row, index }, i) => ({
        index,
        label: row.label || anchorName(index),
        lat: row.lat,
        lon: row.lon,
        geometry: iso[i]?.geometry ?? null,
      })),
      combined: data?.combined?.geometry ?? null,
      pins: placed.map(({ row, index }) => ({
        index,
        label: row.label || anchorName(index),
        lat: row.lat,
        lon: row.lon,
      })),
    };
  }, [rows, data]);

  const urlPoints = useMemo<UrlPoint[]>(
    () =>
      rows.flatMap((row) =>
        hasCoordinates(row)
          ? [{ lat: row.lat, lon: row.lon, mode: row.mode, minutes: row.minutes }]
          : [],
      ),
    [rows],
  );

  const retry = useCallback(() => setNonce((n) => n + 1), []);

  return {
    rows,
    active: rows.length > 0,
    canAdd: rows.length < MAX_TRIP_ROWS,
    lastAddedId,
    status,
    data,
    overlay,
    urlPoints,
    add,
    remove,
    setTravel,
    selectSuggestion,
    submitText,
    clearPlace,
    hydrate,
    retry,
  };
}

export { anchorName };
