import type { Metadata } from "next";
import { Suspense } from "react";
import { preconnect } from "react-dom";

import { Workspace, WorkspaceFallback } from "@/components/Workspace";
import { API_BASE_URL, BASEMAP_ORIGIN, PMTILES_URL, STATIC_URL } from "@/lib/config";

export const metadata: Metadata = {
  title: "App · BenriSpace",
  description: "Score an address or explore the map of convenience scores. Live now in the New York metro area.",
};

/**
 * Origins the map talks to as soon as it loads. Opening their connections while
 * the page's scripts download takes the TLS handshakes off the critical path.
 * Only /app does this, so the home page does not pay for connections it never uses.
 */
const MAP_ORIGINS = [API_BASE_URL, STATIC_URL, PMTILES_URL, BASEMAP_ORIGIN].flatMap(
  (value) => (value ? [new URL(value).origin] : []),
);

export default function AppPage() {
  // fetch() from the page is CORS-mode, so the connection must be too.
  for (const origin of new Set(MAP_ORIGINS)) preconnect(origin, { crossOrigin: "anonymous" });
  return (
    <main
      id="main"
      style={{
        display: "flex",
        flex: 1,
        flexDirection: "column",
        minHeight: 0,
      }}
    >
      <h1 className="sr-only">
        BenriSpace: how convenient is that address?
      </h1>

      {/*
        useSearchParams() opts its subtree out of static prerendering, so
        the boundary keeps the rest of the page static. The fallback is the
        same search form beside an empty map, so the prerendered HTML already
        has the primary control in place and nothing shifts on hydration.
      */}
      <Suspense fallback={<WorkspaceFallback />}>
        <Workspace />
      </Suspense>
    </main>
  );
}
