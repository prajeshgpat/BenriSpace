export const DEFAULT_API_BASE_URL = "http://localhost:8000/v1";

export function resolveApiBaseUrl(value: string | undefined): string {
  const trimmed = value?.trim();
  return (trimmed || DEFAULT_API_BASE_URL).replace(/\/+$/, "");
}

// NEXT_PUBLIC_* is inlined at build time, so this must be a literal property
// access rather than a dynamic lookup.
export const API_BASE_URL = resolveApiBaseUrl(
  process.env.NEXT_PUBLIC_API_BASE_URL,
);

/**
 * How the API scores a location: `grid` (default) reads the stored score of the
 * grid cell, `point` asks it to score the exact spot on demand (`?precision=point`
 * on /score and /area). Set NEXT_PUBLIC_SCORE_PRECISION=point to try it.
 */
export type ScorePrecision = "grid" | "point";

export function resolveScorePrecision(value: string | undefined): ScorePrecision {
  return value?.trim().toLowerCase() === "point" ? "point" : "grid";
}

export const SCORE_PRECISION = resolveScorePrecision(
  process.env.NEXT_PUBLIC_SCORE_PRECISION,
);

/**
 * Optional streaming chat endpoint (a Lambda function URL, see
 * docs/ARCHITECTURE.md "Chat streaming"). Unset means chat uses plain `/chat`.
 */
export function resolveChatStreamUrl(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  if (!trimmed) return undefined;
  try {
    return new URL(trimmed).toString();
  } catch {
    return undefined;
  }
}
export const CHAT_STREAM_URL = resolveChatStreamUrl(
  process.env.NEXT_PUBLIC_CHAT_STREAM_URL,
);

/**
 * Optional PMTiles archive of the cell grid and area polygons (built by
 * scripts/build_tiles.py, hosted on R2). Unset means the map draws cells from
 * GeoJSON as before. https only, or localhost for development.
 */
export function resolveTilesUrl(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  if (!trimmed) return undefined;
  try {
    const url = new URL(trimmed);
    const local = url.hostname === "localhost" || url.hostname === "127.0.0.1";
    return url.protocol === "https:" || (local && url.protocol === "http:")
      ? url.toString()
      : undefined;
  } catch {
    return undefined;
  }
}
export const PMTILES_URL = resolveTilesUrl(process.env.NEXT_PUBLIC_PMTILES_URL);

/**
 * Every host the map needs lives here: the style JSON, vector tiles, glyphs
 * and sprites are all served from this one origin. next.config.ts builds the
 * Content-Security-Policy from it, so changing the basemap provider is a
 * one-line edit.
 */
export const BASEMAP_ORIGIN = "https://tiles.openfreemap.org";
export const BASEMAP_STYLE_URLS = {
  light: `${BASEMAP_ORIGIN}/styles/liberty`,
  dark: `${BASEMAP_ORIGIN}/styles/dark`,
} as const;
