import type { Metadata } from "next";
import { Suspense } from "react";

import { Workspace, WorkspaceFallback } from "@/components/Workspace";

export const metadata: Metadata = {
  title: "App · BenriSpace",
  description: "Score an address or explore the map of convenience scores across the New York metro area.",
};

export default function AppPage() {
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
