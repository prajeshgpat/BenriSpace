import type { Metadata } from "next";
import { Suspense } from "react";

import { MapLoader } from "@/components/map/MapLoader";
import { SITE_NAME } from "@/lib/site";

export const metadata: Metadata = {
  title: `Explore the map · ${SITE_NAME}`,
  description:
    "See where in the New York metro area scores best on groceries, transit, schools, trails and more, and choose which factors matter to you.",
};

export default function MapPage() {
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
      <h1 className="sr-only">Explore the convenience map</h1>
      <Suspense fallback={null}>
        <MapLoader />
      </Suspense>
    </main>
  );
}
