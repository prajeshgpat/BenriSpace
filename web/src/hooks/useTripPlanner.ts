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

/** At most two points of interest, besides the searched place. */
export const MAX_POIS = 2;
/** Wait for the last edit before asking the server. */
export const TRIANGULATE_DEBOUNCE_MS = 400;
/** Overlap results closer than this are one place to the reader. */
export const MIN_RESULT_SEPARATION_MI = 0.25;
export const MAX_TRIP_RESULTS = 5;
export const NOT_FOUND_MESSAGE = "Couldn't find that address. Pick one from the list.";

/** A point of interest. Its travel mode and minutes come from the Travel time row. */
export interface TripRow {
  id: string;
  /** The confirmed place's name (or what was submitted). */
  label: string;
  lat?: number;
  lon?: number;
  /** What is typed in the box right now, when it was never confirmed. */
  draft?: string;
  /** Set when typed text could not be resolved to a place. */
  error: string | null;
}

/** The place being scored: the first anchor. */
export interface TripPlace {
  label: string;
  lat: number;
  lon: number;
}

/** The shared Travel time row: every anchor uses it. */
export interface TripTravel {
  mode: ReachMode;
  minutes: number;
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
  /** 0 = the searched place, 1 and 2 = points of interest. */
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
  return index === 0 ? "Searched place" : `Point of interest ${index}`;
}

/** Does this typed text still need resolving to a place? */
function needsResolving(row: TripRow): boolean {
  const text = row.draft?.trim() ?? "";
  if (text === "") return false;
  return !hasCoordinates(row) || text !== row.label;
}

type Settled =
  | { key: string; status: "ready" | "empty"; data: TripData }
  | { key: string; status: "error" };


export interface TripPlannerState {
  /** The points of interest, in order (at most two). */
  rows: TripRow[];
  /** Any point of interest exists: the single-place travel area steps aside. */
  active: boolean;
  /** The "+ Point of interest" control is usable. */
  canAdd: boolean;
  /** Id of the row added by the last `add`, so the UI can focus it. */
  lastAddedId: string | null;
  status: TripStatus;
  data: TripData | null;
  overlay: TripOverlay;
  /** Points with coordinates, for the shared URL. */
  urlPoints: UrlPoint[];
  add: () => void;
  remove: (id: string) => void;
  /** A suggestion was picked for this row. */
  selectSuggestion: (id: string, suggestion: Suggestion) => void;
  /** Typed text was submitted without picking a suggestion. */
  submitText: (id: string, text: string) => void;
  /** Every keystroke in the row's box, so unconfirmed text can be resolved later. */
  setText: (id: string, text: string) => void;
  /** Forget the row's place. */
  clearPlace: (id: string) => void;
  /** Resolve every box whose text was never confirmed; settles when all are done. */
  resolvePending: () => Promise<void>;
  /** A tap on the map while this box was selected: use that place, labelled by its address. */
  setPlaceFromMap: (id: string, point: { lat: number; lon: number }) => void;
  /** Rebuild the planner from URL points; labels are looked up afterwards. */
  hydrate: (points: readonly UrlPoint[]) => void;
  retry: () => void;
}

/**
 * The state behind the "+ Point of interest" planner: up to two points of interest,
 * a debounced call to `POST /triangulate` for the searched place plus those points
 * (all with the shared Travel time), and the spread-out list of best areas in the overlap.
 */
export function useTripPlanner(
  client: ClientSubset,
  place: TripPlace | null,
  travel: TripTravel | null,
): TripPlannerState {
  const [rows, setRows] = useState<TripRow[]>([]);
  const [lastAddedId, setLastAddedId] = useState<string | null>(null);
  const [settled, setSettled] = useState<Settled | null>(null);
  const [nonce, setNonce] = useState(0);
  const counter = useRef(0);
  const resolving = useRef(new Map<string, number>());
  const labels = useRef(new Map<string, string | null>());
  const clientRef = useRef(client);
  const rowsRef = useRef(rows);
  useEffect(() => {
    clientRef.current = client;
    rowsRef.current = rows;
  });

  const nextId = () => `trip-${(counter.current += 1)}`;

  const patchRow = useCallback((id: string, patch: Partial<TripRow>) => {
    setRows((current) => current.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  }, []);

  const add = useCallback(() => {
    if (rows.length >= MAX_POIS) return;
    const point: TripRow = { id: nextId(), label: "", error: null };
    setLastAddedId(point.id);
    setRows([...rows, point]);
  }, [rows]);

  const remove = useCallback((id: string) => {
    resolving.current.delete(id);
    setRows((current) => current.filter((r) => r.id !== id));
  }, []);

  const selectSuggestion = useCallback(
    (id: string, suggestion: Suggestion) => {
      resolving.current.delete(id);
      patchRow(id, {
        label: suggestion.label,
        lat: suggestion.latitude,
        lon: suggestion.longitude,
        draft: undefined,
        error: null,
      });
    },
    [patchRow],
  );

  const clearPlace = useCallback(
    (id: string) => {
      resolving.current.delete(id);
      patchRow(id, { label: "", lat: undefined, lon: undefined, draft: undefined, error: null });
    },
    [patchRow],
  );

  const setText = useCallback(
    (id: string, text: string) => {
      if (text.trim() === "") {
        clearPlace(id);
        return;
      }
      patchRow(id, { draft: text, error: null });
    },
    [patchRow, clearPlace],
  );

  const setPlaceFromMap = useCallback(
    (id: string, point: { lat: number; lon: number }) => {
      resolving.current.delete(id);
      const fallback = formatLatLon(point);
      patchRow(id, { label: fallback, lat: point.lat, lon: point.lon, draft: undefined, error: null });
      clientRef.current
        .reverseGeocode(point)
        .then(({ label }) => {
          if (!label) return;
          // Only replace the stand-in if the box still holds this tapped place.
          setRows((current) =>
            current.map((r) =>
              r.id === id && r.lat === point.lat && r.lon === point.lon && r.label === fallback
                ? { ...r, label }
                : r,
            ),
          );
        })
        .catch(() => {});
    },
    [patchRow],
  );

  const resolveText = useCallback(
    (id: string, text: string): Promise<void> => {
      const query = text.trim();
      if (query === "") return Promise.resolve();
      const token = (resolving.current.get(id) ?? 0) + 1;
      resolving.current.set(id, token);
      return clientRef.current
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
            draft: undefined,
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

  const submitText = useCallback(
    (id: string, text: string) => {
      void resolveText(id, text);
    },
    [resolveText],
  );

  const resolvePending = useCallback(async () => {
    const pending = rowsRef.current.filter(needsResolving);
    await Promise.all(pending.map((row) => resolveText(row.id, row.draft as string)));
  }, [resolveText]);

  const hydrate = useCallback(
    (points: readonly UrlPoint[]) => {
      const restored: TripRow[] = points.slice(0, MAX_POIS).map((p) => ({
        id: nextId(),
        label: formatLatLon(p),
        lat: p.lat,
        lon: p.lon,
        error: null,
      }));
      setRows(restored);
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

  // Index 0 is the searched place, then the points of interest that have a place.
  const placed = useMemo(() => {
    const list: { index: number; label: string; lat: number; lon: number }[] = [];
    if (place) {
      list.push({ index: 0, label: place.label || anchorName(0), lat: place.lat, lon: place.lon });
    }
    rows.forEach((row, i) => {
      if (hasCoordinates(row)) {
        list.push({
          index: i + 1,
          label: row.label || anchorName(i + 1),
          lat: row.lat,
          lon: row.lon,
        });
      }
    });
    return list;
  }, [place, rows]);

  const mode = travel?.mode;
  const minutes = travel?.minutes;
  const anchors = useMemo<TriangulateAnchor[]>(
    () =>
      mode === undefined || minutes === undefined
        ? []
        : placed.map((p) => ({ label: p.label, lat: p.lat, lon: p.lon, mode, minutes })),
    [placed, mode, minutes],
  );
  const hasPoi = placed.some((p) => p.index > 0);
  const anchorKey =
    place && hasPoi && anchors.length >= 2 ? `${JSON.stringify(anchors)}#${nonce}` : null;

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
    const iso = data?.isochrones ?? [];
    return {
      anchors: placed.map((p, i) => ({ ...p, geometry: iso[i]?.geometry ?? null })),
      combined: data?.combined?.geometry ?? null,
      pins: placed.map((p) => ({ ...p })),
    };
  }, [placed, data]);

  const urlPoints = useMemo<UrlPoint[]>(
    () => rows.flatMap((row) => (hasCoordinates(row) ? [{ lat: row.lat, lon: row.lon }] : [])),
    [rows],
  );

  const retry = useCallback(() => setNonce((n) => n + 1), []);

  return {
    rows,
    active: rows.length > 0,
    canAdd: rows.length < MAX_POIS,
    lastAddedId,
    status,
    data,
    overlay,
    urlPoints,
    add,
    remove,
    selectSuggestion,
    submitText,
    setText,
    clearPlace,
    resolvePending,
    setPlaceFromMap,
    hydrate,
    retry,
  };
}

export { anchorName };
