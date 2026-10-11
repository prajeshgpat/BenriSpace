"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { formatLatLon } from "@/lib/address";
import type { ApiClient } from "@/lib/api/client";
import { FACTOR_KEY_LIST } from "@/lib/api/types";
import type {
  AreaGeometry,
  FactorKey,
  Isochrone,
  PriorityQuery,
  ReachMode,
  Suggestion,
  TriangulateAnchor,
} from "@/lib/api/types";
import type { UrlPoint } from "@/lib/map/url";
import { selectionScore } from "@/lib/scores/matrix";
import { distanceMi } from "@/lib/travel";

export { distanceMi };

/** At most two points of interest, besides the searched place. */
export const MAX_POIS = 2;
/** Wait for the last edit before asking the server. */
export const TRIANGULATE_DEBOUNCE_MS = 400;
/** Overlap results closer than this are one place to the reader. */
export const MIN_RESULT_SEPARATION_MI = 0.25;
export const MAX_TRIP_RESULTS = 5;
export const NOT_FOUND_MESSAGE = "Couldn't find that address. Pick one from the list.";

/** A point of interest. Its travel mode and minutes follow the Travel time row until set here. */
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
  /** This point's own travel mode; undefined follows the main Travel time row. */
  mode?: ReachMode;
  /** This point's own minutes; undefined follows the main Travel time row. */
  minutes?: number;
}

/** The place being scored: the first anchor. */
export interface TripPlace {
  label: string;
  lat: number;
  lon: number;
}

/** The main Travel time row: the searched place uses it, and so does any point not set apart. */
export interface TripTravel {
  mode: ReachMode;
  minutes: number;
}

/** What a point of interest travels by: its own choice, else the main Travel time. */
export function effectiveTravel(row: TripRow, travel: TripTravel): TripTravel {
  return { mode: row.mode ?? travel.mode, minutes: row.minutes ?? travel.minutes };
}

export interface TripResult {
  lat: number;
  lon: number;
  /**
   * The user's factor-normalised score for this area: what the "Area in the overlap" card
   * shows. Falls back to the API's composite when the area's sub-scores can't be fetched.
   */
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

type ClientSubset = Pick<ApiClient, "triangulate" | "reverseGeocode" | "suggestAddresses"> &
  Partial<Pick<ApiClient, "getAreaByCoordinates">>;

/** The user's selected factors and importance, which the overlap is ranked and scored by. */
export interface TripPriorities {
  factors: readonly FactorKey[];
  weights?: Partial<Record<FactorKey, number>>;
}

/** What `POST /triangulate` is sent: no `factors` when all are selected, like the map calls. */
function priorityRequest(priorities: TripPriorities | undefined): PriorityQuery {
  if (!priorities || priorities.factors.length === 0) return {};
  return {
    factors: priorities.factors.length === FACTOR_KEY_LIST.length ? undefined : priorities.factors,
    weights: priorities.weights,
  };
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
  /** At least one point of interest has a place: the single-place results step aside. */
  hasPlaces: boolean;
  /** The main Travel time, which points of interest follow unless set apart. */
  travel: TripTravel | null;
  /** The box that is waiting for a pin dropped on the map (or for typing), if any. */
  armedId: string | null;
  arm: (id: string | null) => void;
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
  /** Give one point its own travel mode and minutes. */
  setTravel: (id: string, mode: ReachMode, minutes: number) => void;
  /** Forget the row's place. */
  clearPlace: (id: string) => void;
  /** Resolve every box whose text was never confirmed; settles when all are done. */
  resolvePending: () => Promise<void>;
  /** A tap on the map while this box was selected: use that place, labelled by its address. */
  setPlaceFromMap: (id: string, point: { lat: number; lon: number }) => void;
  /** Rebuild the planner from points (a shared URL, a chat answer); missing labels are looked up. */
  hydrate: (points: readonly (UrlPoint & { label?: string })[]) => void;
  retry: () => void;
}

/**
 * The state behind the "+ Point of interest" planner: up to two points of interest,
 * a debounced call to `POST /triangulate` for the searched place plus those points
 * (all with the shared Travel time), and the spread-out list of best areas in the overlap.
 * With `priorities`, the overlap is ranked by the selected factors and each listed area's
 * score is the one the score card shows for it (its sub-scores over those factors).
 */
export function useTripPlanner(
  client: ClientSubset,
  place: TripPlace | null,
  travel: TripTravel | null,
  priorities?: TripPriorities,
): TripPlannerState {
  const [rows, setRows] = useState<TripRow[]>([]);
  const [lastAddedId, setLastAddedId] = useState<string | null>(null);
  const [armedId, setArmedId] = useState<string | null>(null);
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

  // What the score card shows for each area, by the same call and arithmetic; undefined
  // where the area can't be looked up, so the API's score stands in.
  const selectionScores = (
    areas: readonly { lat: number; lon: number }[],
    selected: TripPriorities | undefined,
    signal: AbortSignal,
  ): Promise<(number | undefined)[]> => {
    const lookup = clientRef.current.getAreaByCoordinates;
    if (!selected || selected.factors.length === 0 || !lookup) {
      return Promise.resolve(areas.map(() => undefined));
    }
    return Promise.all(
      areas.map((area) =>
        lookup
          .call(clientRef.current, { lat: area.lat, lon: area.lon }, { signal })
          .then((found) => selectionScore(found.score.subScores, selected.factors, selected.weights))
          .then((score) => score ?? undefined)
          .catch(() => undefined),
      ),
    );
  };

  const nextId = () => `trip-${(counter.current += 1)}`;

  const patchRow = useCallback((id: string, patch: Partial<TripRow>) => {
    setRows((current) => current.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  }, []);

  const add = useCallback(() => {
    if (rows.length >= MAX_POIS) return;
    const point: TripRow = { id: nextId(), label: "", error: null };
    setLastAddedId(point.id);
    // A new box waits for a pin on the map; the keyboard only opens on a second tap.
    setArmedId(point.id);
    setRows([...rows, point]);
  }, [rows]);

  const remove = useCallback((id: string) => {
    resolving.current.delete(id);
    setArmedId((current) => (current === id ? null : current));
    setRows((current) => current.filter((r) => r.id !== id));
  }, []);

  const setTravel = useCallback(
    (id: string, mode: ReachMode, minutes: number) => patchRow(id, { mode, minutes }),
    [patchRow],
  );

  const selectSuggestion = useCallback(
    (id: string, suggestion: Suggestion) => {
      resolving.current.delete(id);
      setArmedId((current) => (current === id ? null : current));
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
      setArmedId((current) => (current === id ? null : current));
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
    (points: readonly (UrlPoint & { label?: string })[]) => {
      const restored: TripRow[] = points.slice(0, MAX_POIS).map((p) => ({
        id: nextId(),
        label: p.label?.trim() || formatLatLon(p),
        lat: p.lat,
        lon: p.lon,
        error: null,
      }));
      setArmedId(null);
      setRows(restored);
      for (const row of restored) {
        if (row.label !== formatLatLon(row as { lat: number; lon: number })) continue;
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
    const list: {
      index: number;
      label: string;
      lat: number;
      lon: number;
      mode?: ReachMode;
      minutes?: number;
    }[] = [];
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
          mode: row.mode,
          minutes: row.minutes,
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
        : placed.map((p) => ({
            label: p.label,
            lat: p.lat,
            lon: p.lon,
            // The searched place always uses the main Travel time.
            mode: p.index === 0 ? mode : (p.mode ?? mode),
            minutes: p.index === 0 ? minutes : (p.minutes ?? minutes),
          })),
    [placed, mode, minutes],
  );
  const hasPoi = placed.some((p) => p.index > 0);
  const query = useMemo(() => priorityRequest(priorities), [priorities]);
  const queryKey = JSON.stringify([
    query.factors ?? null,
    Object.entries(query.weights ?? {}).sort(([a], [b]) => (a < b ? -1 : 1)),
  ]);
  const anchorKey =
    place && hasPoi && anchors.length >= 2
      ? `${JSON.stringify(anchors)}|${queryKey}#${nonce}`
      : null;

  useEffect(() => {
    if (anchorKey === null) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      clientRef.current
        .triangulate(anchors, { ...query, signal: controller.signal })
        .then(async (response) => {
          if (controller.signal.aborted) return;
          const picked = pickSpreadResults(response.results);
          const scores = await selectionScores(picked, priorities, controller.signal);
          if (controller.signal.aborted) return;
          const spread = picked
            .map<TripResult>((r, i) => ({
              lat: r.lat,
              lon: r.lon,
              score: scores[i] ?? r.score,
              label:
                COORDINATE_TEXT.test(r.address) || r.address === "" ? formatLatLon(r) : r.address,
            }))
            .sort((a, b) => b.score - a.score);
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
      anchors: placed.map((p, i) => ({
        index: p.index,
        label: p.label,
        lat: p.lat,
        lon: p.lon,
        geometry: iso[i]?.geometry ?? null,
      })),
      combined: data?.combined?.geometry ?? null,
      pins: placed.map((p) => ({ index: p.index, label: p.label, lat: p.lat, lon: p.lon })),
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
    hasPlaces: urlPoints.length > 0,
    travel,
    armedId,
    arm: setArmedId,
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
    setTravel,
    clearPlace,
    resolvePending,
    setPlaceFromMap,
    hydrate,
    retry,
  };
}

export { anchorName };
