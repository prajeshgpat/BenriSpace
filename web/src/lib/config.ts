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
