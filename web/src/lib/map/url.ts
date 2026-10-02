import type { FactorKey } from "@/lib/api/types";
import { FACTOR_KEYS } from "@/lib/score/factors";

import {
  ALL_FACTORS,
  createSelection,
  isAllSelected,
  type FactorSelection,
  type ImportanceOverrides,
} from "./selection";
import { viewParams, type MapView } from "./viewport";

export type TopScope = "metro" | "view";

export interface MapUrlState {
  /** `null` means "fit the covered metro". */
  view: MapView | null;
  selection: FactorSelection;
  scope: TopScope;
}

export const DEFAULT_MAP_STATE: MapUrlState = {
  view: null,
  selection: ALL_FACTORS,
  scope: "metro",
};

const MIN_ZOOM = 3;
const MAX_ZOOM = 19;

const isFactorKey = (value: string): value is FactorKey =>
  (FACTOR_KEYS as readonly string[]).includes(value);

function number(raw: string | null): number | null {
  if (raw === null || raw.trim() === "") return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

function parseView(params: URLSearchParams): MapView | null {
  const lat = number(params.get("lat"));
  const lon = number(params.get("lon"));
  if (
    lat === null ||
    lon === null ||
    Math.abs(lat) > 90 ||
    Math.abs(lon) > 180
  ) {
    return null;
  }
  const zoom = number(params.get("z"));
  return {
    lat,
    lon,
    zoom: Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom ?? 12)),
  };
}

function parseFactors(raw: string | null): FactorKey[] | null {
  if (raw === null) return null;
  if (raw === "none") return [];
  const keys = raw.split(",").filter(isFactorKey);
  return keys.length > 0 ? keys : null;
}

function parseImportance(raw: string | null): ImportanceOverrides {
  const overrides: ImportanceOverrides = {};
  for (const pair of raw?.split(",") ?? []) {
    const [key, level] = pair.split(":");
    if (isFactorKey(key) && (level === "low" || level === "high")) {
      overrides[key] = level;
    }
  }
  return overrides;
}

/** Unknown or malformed values fall back to defaults instead of erroring. */
export function parseMapParams(params: URLSearchParams): MapUrlState {
  const factors = parseFactors(params.get("factors"));
  return {
    view: parseView(params),
    selection: createSelection(
      factors ?? FACTOR_KEYS,
      parseImportance(params.get("importance")),
    ),
    scope: params.get("scope") === "view" ? "view" : "metro",
  };
}

/** Defaults are omitted so the shared URL stays short. */
export function serializeMapParams({
  view,
  selection,
  scope,
}: MapUrlState): string {
  const params = new URLSearchParams();
  if (view) viewParams(view).forEach((value, key) => params.set(key, value));
  if (selection.factors.length === 0) {
    params.set("factors", "none");
  } else if (!isAllSelected(selection)) {
    params.set("factors", selection.factors.join(","));
  }
  const importance = Object.entries(selection.importance);
  if (importance.length > 0) {
    params.set("importance", importance.map(([k, v]) => `${k}:${v}`).join(","));
  }
  if (scope === "view") params.set("scope", "view");
  return params.toString();
}
