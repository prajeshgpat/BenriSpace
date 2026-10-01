import type { NextConfig } from "next";

import { resolveApiBaseUrl } from "./src/lib/config";

const apiOrigin = new URL(
  resolveApiBaseUrl(process.env.NEXT_PUBLIC_API_BASE_URL),
).origin;

// Statically prerendered pages cannot carry a per-request nonce, so scripts
// and styles fall back to 'unsafe-inline'. The policy still pins network
// access to this origin and the API, which is what keeps third-party
// trackers out.
const contentSecurityPolicy = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self'",
  `connect-src 'self' ${apiOrigin}`,
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
    value: "camera=(), microphone=(), geolocation=(), browsing-topics=()",
  },
  // The dev server needs eval and a websocket for fast refresh.
  ...(process.env.NODE_ENV === "production"
    ? [{ key: "Content-Security-Policy", value: contentSecurityPolicy }]
    : []),
];

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Pin tracing to this app so a lockfile elsewhere on the machine cannot
  // change what gets bundled.
  outputFileTracingRoot: __dirname,
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
