import type { NextConfig } from "next";

import {
  BASEMAP_ORIGIN,
  resolveApiBaseUrl,
  resolveChatStreamUrl,
  resolveTilesUrl,
} from "./src/lib/config";

const apiOrigin = new URL(
  resolveApiBaseUrl(process.env.NEXT_PUBLIC_API_BASE_URL),
).origin;

// Optional extra origins: the streaming chat endpoint and the PMTiles bucket.
const extraConnectOrigins = [
  resolveChatStreamUrl(process.env.NEXT_PUBLIC_CHAT_STREAM_URL),
  resolveTilesUrl(process.env.NEXT_PUBLIC_PMTILES_URL),
].flatMap((value) => (value ? [new URL(value).origin] : []));

// Statically prerendered pages cannot carry a per-request nonce, so scripts
// and styles fall back to 'unsafe-inline'. The policy still pins network
// access to this origin and the API, which is what keeps third-party
// trackers out.
const contentSecurityPolicy = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  // MapLibre fetches the style, TileJSON, vector tiles, glyphs and sprites
  // from the basemap origin with fetch() (connect-src) and decodes sprite and
  // raster tiles into images (img-src). Its tile parsing runs in a Web Worker
  // that it starts from a Blob URL (worker-src, with child-src for Safari).
  `img-src 'self' data: blob: ${BASEMAP_ORIGIN}`,
  "font-src 'self'",
  `connect-src ${["'self'", apiOrigin, BASEMAP_ORIGIN, ...extraConnectOrigins].join(" ")}`,
  "worker-src 'self' blob:",
  "child-src 'self' blob:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(self), browsing-topics=()",
  },
  // The dev server needs eval and a websocket for fast refresh.
  ...(process.env.NODE_ENV === "production"
    ? [{ key: "Content-Security-Policy", value: contentSecurityPolicy }]
    : []),
];

/**
 * Query keys the app writes to the URL. Old shared links put them on `/`,
 * which is now the static home page, so each one forwards to `/app`. Next
 * keeps the original query string on a redirect whose destination has no
 * query of its own, so the whole link survives.
 */
export const LEGACY_APP_QUERY_KEYS = [
  "address",
  "lat",
  "lon",
  "center",
  "z",
  "factors",
  "importance",
  "scope",
] as const;

export function legacyAppRedirects() {
  return LEGACY_APP_QUERY_KEYS.map((key) => ({
    source: "/",
    has: [{ type: "query" as const, key }],
    destination: "/app",
    permanent: false,
  }));
}

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Pin tracing to this app so a lockfile elsewhere on the machine cannot
  // change what gets bundled.
  outputFileTracingRoot: __dirname,
  async redirects() {
    return legacyAppRedirects();
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
