import {
  formatLatLon,
  resolveTarget,
  type LatLon,
  type ScoreTarget,
} from "@/lib/address";
import type { FactorKey } from "@/lib/api/types";
import { FACTOR_KEYS, canonicalFactorKey } from "@/lib/score/factors";
import { APP_PATH } from "@/lib/site";

import {
  createSelection,
  isAllSelected,
  type FactorSelection,
  type ImportanceOverrides,
} from "./selection";
import type { MapView } from "./viewport";

/** The state of the whole page; every part of it can be shared as a URL. */
export interface ExplorerUrlState {
  /** The place being scored, from `address`, or `lat` and `lon`. */
  target: ScoreTarget | null;
  /** A centre the user panned to (`center`), when it differs from the target. */
  center: LatLon | null;
  zoom: number | null;
  selection: FactorSelection;
}

const MIN_ZOOM = 3;
const MAX_ZOOM = 19;
/** Zoom for a scored place with no zoom in the URL: a few blocks across. */
export const PLACE_ZOOM = 14;
const DEFAULT_CENTER_ZOOM = 12;


function number(raw: string | null | undefined): number | null {
  if (raw === null || raw === undefined || raw.trim() === "") return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

function parseCenter(raw: string | null): LatLon | null {
  const [lat, lon, ...rest] = (raw ?? "").split(",").map(number);
  if (
    rest.length > 0 ||
    lat === null ||
    lat === undefined ||
    lon === null ||
    lon === undefined ||
    Math.abs(lat) > 90 ||
    Math.abs(lon) > 180
  ) {
    return null;
  }
  return { lat, lon };
}

function parseZoom(raw: string | null): number | null {
  const zoom = number(raw);
  return zoom === null ? null : Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom));
}

function parseFactors(raw: string | null): FactorKey[] | null {
  if (raw === null) return null;
  if (raw === "none") return [];
  const keys = [
    ...new Set(raw.split(",").flatMap((key) => canonicalFactorKey(key) ?? [])),
  ];
  return keys.length > 0 ? keys : null;
}

function parseImportance(raw: string | null): ImportanceOverrides {
  const overrides: ImportanceOverrides = {};
  for (const pair of raw?.split(",") ?? []) {
    const [rawKey, level] = pair.split(":");
    const key = canonicalFactorKey(rawKey);
    if (key !== null && (level === "low" || level === "high")) {
      overrides[key] = level;
    }
  }
  return overrides;
}

/** Unknown or malformed values fall back to defaults instead of erroring. */
export function parseExplorerParams(
  params: URLSearchParams,
): ExplorerUrlState & { targetError: string | null } {
  const { target, error } = resolveTarget(params);
  return {
    target,
    targetError: error,
    center: parseCenter(params.get("center")),
    zoom: parseZoom(params.get("z")),
    selection: createSelection(
      parseFactors(params.get("factors")) ?? FACTOR_KEYS,
      parseImportance(params.get("importance")),
    ),
  };
}

/** Where the map should open: the URL's view, else the scored place. */
export function initialView(
  state: Pick<ExplorerUrlState, "target" | "center" | "zoom">,
): MapView | null {
  if (state.center) {
    return { ...state.center, zoom: state.zoom ?? DEFAULT_CENTER_ZOOM };
  }
  if (state.target?.kind === "coordinates") {
    return {
      lat: state.target.lat,
      lon: state.target.lon,
      zoom: state.zoom ?? PLACE_ZOOM,
    };
  }
  return null;
}

export interface ExplorerUrlInput {
  target: ScoreTarget | null;
  /** Left out until the map has something worth restoring. */
  view: MapView | null;
  selection: FactorSelection;
}

function formatCentre({ lat, lon }: LatLon): string {
  return `${lat.toFixed(4)},${lon.toFixed(4)}`;
}

/** Defaults are omitted so the shared URL stays short. */
export function serializeExplorerParams({
  target,
  view,
  selection,
}: ExplorerUrlInput): string {
  const params = new URLSearchParams();
  if (target?.kind === "address") {
    params.set("address", target.address);
  } else if (target) {
    if (target.label !== formatLatLon(target)) params.set("address", target.label);
    params.set("lat", String(target.lat));
    params.set("lon", String(target.lon));
  }
  if (view) {
    const centre = formatCentre(view);
    const atTarget = target?.kind === "coordinates" && centre === formatCentre(target);
    if (!atTarget) params.set("center", centre);
    params.set("z", String(Math.round(view.zoom * 100) / 100));
  }
  if (selection.factors.length === 0) {
    params.set("factors", "none");
  } else if (!isAllSelected(selection)) {
    params.set("factors", selection.factors.join(","));
  }
  const importance = Object.entries(selection.importance);
  if (importance.length > 0) {
    params.set("importance", importance.map(([k, v]) => `${k}:${v}`).join(","));
  }
  return params.toString();
}

export function explorerHref(input: ExplorerUrlInput): string {
  const query = serializeExplorerParams(input);
  return query ? `${APP_PATH}?${query}` : APP_PATH;
}

/**
 * The old `/map` page used `lat` and `lon` for the view centre; on the
 * single page they select a place, so the redirect renames them. Everything
 * else carries over unchanged.
 */
export function legacyMapQuery(
  source: Record<string, string | string[] | undefined>,
): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(source)) {
    const first = Array.isArray(value) ? value[0] : value;
    if (first !== undefined) params.set(key, first);
  }
  const centre = parseCenter(`${params.get("lat")},${params.get("lon")}`);
  params.delete("lat");
  params.delete("lon");
  if (centre && !params.has("center")) params.set("center", formatCentre(centre));
  return params.toString();
}
