import { FACTOR_KEY_LIST, type FactorKey, type SubScores } from "@/lib/api/types";
import { roundScore } from "@/lib/score/presentation";

export const MAX_COMPARE = 4;
export const COMPARE_STORAGE_KEY = "benrispace.compare.v1";

export interface ComparePlace {
  /** Stable identity: the place's coordinates. */
  id: string;
  label: string;
  neighborhood: string | null;
  score: number;
  subScores: SubScores;
  lat: number;
  lon: number;
}

export function placeId(lat: number, lon: number): string {
  return `${lat.toFixed(4)},${lon.toFixed(4)}`;
}

export function addPlace(
  places: readonly ComparePlace[],
  place: ComparePlace,
): ComparePlace[] {
  if (places.some((p) => p.id === place.id)) return [...places];
  if (places.length >= MAX_COMPARE) return [...places];
  return [...places, place];
}

export function removePlace(
  places: readonly ComparePlace[],
  id: string,
): ComparePlace[] {
  return places.filter((p) => p.id !== id);
}

export type CompareRow = "overall" | FactorKey;
export const COMPARE_ROWS: readonly CompareRow[] = ["overall", ...FACTOR_KEY_LIST];

/** A place's value in a row, rounded for display; null when there is no score. */
export function rowValue(place: ComparePlace, row: CompareRow): number | null {
  const raw = row === "overall" ? place.score : place.subScores[row];
  return raw === null || raw === undefined || !Number.isFinite(raw)
    ? null
    : roundScore(raw);
}

/**
 * Ids of the places holding the best value in a row. Ties all win; nothing is
 * highlighted when fewer than two places have a value (nothing to compare).
 */
export function bestInRow(
  places: readonly ComparePlace[],
  row: CompareRow,
): Set<string> {
  const values = places.flatMap((p) => {
    const v = rowValue(p, row);
    return v === null ? [] : [{ id: p.id, v }];
  });
  if (values.length < 2) return new Set();
  const best = Math.max(...values.map((x) => x.v));
  return new Set(values.filter((x) => x.v === best).map((x) => x.id));
}

/** Points a place trails the row's best value by (0 for the best, null without data). */
export function gapFromBest(
  places: readonly ComparePlace[],
  place: ComparePlace,
  row: CompareRow,
): number | null {
  const own = rowValue(place, row);
  if (own === null) return null;
  const values = places.flatMap((p) => {
    const v = rowValue(p, row);
    return v === null ? [] : [v];
  });
  if (values.length < 2) return null;
  return Math.max(...values) - own;
}

export interface RowDifference {
  row: FactorKey;
  /** Best minus worst value across the pinned places. */
  spread: number;
  leaderIds: string[];
  trailerIds: string[];
}

/**
 * The factors where the pinned places differ most, largest spread first.
 * Rows with fewer than two values or a spread under `minSpread` are left out.
 */
export function biggestDifferences(
  places: readonly ComparePlace[],
  limit = 3,
  minSpread = 5,
): RowDifference[] {
  if (places.length < 2) return [];
  const out: RowDifference[] = [];
  for (const row of FACTOR_KEY_LIST) {
    const values = places.flatMap((p) => {
      const v = rowValue(p, row);
      return v === null ? [] : [{ id: p.id, v }];
    });
    if (values.length < 2) continue;
    const hi = Math.max(...values.map((x) => x.v));
    const lo = Math.min(...values.map((x) => x.v));
    if (hi - lo < minSpread) continue;
    out.push({
      row,
      spread: hi - lo,
      leaderIds: values.filter((x) => x.v === hi).map((x) => x.id),
      trailerIds: values.filter((x) => x.v === lo).map((x) => x.id),
    });
  }
  return out.sort((a, b) => b.spread - a.spread).slice(0, limit);
}

function isPlace(value: unknown): value is ComparePlace {
  if (typeof value !== "object" || value === null) return false;
  const p = value as Record<string, unknown>;
  return (
    typeof p.id === "string" &&
    typeof p.label === "string" &&
    typeof p.score === "number" &&
    typeof p.lat === "number" &&
    typeof p.lon === "number" &&
    typeof p.subScores === "object" &&
    p.subScores !== null
  );
}

export function loadPlaces(): ComparePlace[] {
  try {
    const raw = window.sessionStorage.getItem(COMPARE_STORAGE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed)
      ? parsed.filter(isPlace).slice(0, MAX_COMPARE)
      : [];
  } catch {
    return [];
  }
}

export function savePlaces(places: readonly ComparePlace[]): void {
  try {
    if (places.length === 0) window.sessionStorage.removeItem(COMPARE_STORAGE_KEY);
    else window.sessionStorage.setItem(COMPARE_STORAGE_KEY, JSON.stringify(places));
  } catch {
    // Private mode or a full quota: the pins just are not kept.
  }
}
