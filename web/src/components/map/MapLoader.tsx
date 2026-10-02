"use client";

import dynamic from "next/dynamic";
import { useSearchParams } from "next/navigation";
import { useState } from "react";

import { parseMapParams } from "@/lib/map/url";

import styles from "./MapLoader.module.css";

// MapLibre is large and WebGL-only: keep it out of every other route's
// bundle and out of server rendering.
const MapExplorer = dynamic(
  () => import("./MapExplorer").then((module) => module.MapExplorer),
  { ssr: false, loading: () => <MapPlaceholder /> },
);

function MapPlaceholder() {
  return (
    <div className={styles.placeholder} role="status">
      Loading the map…
    </div>
  );
}

export function MapLoader() {
  const params = useSearchParams();
  // Read once. After this the page owns the URL and only writes to it.
  const [initial] = useState(() => parseMapParams(params));
  return <MapExplorer initial={initial} />;
}
