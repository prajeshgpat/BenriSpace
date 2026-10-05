"use client";

import { useEffect, useState } from "react";

import { PMTILES_URL, STATIC_URL } from "@/lib/config";
import { decodeAreaScores, type AreaScores } from "@/lib/static/areaScores";
import { loadStaticPiece, loadStaticTilesUrl } from "@/lib/static/manifest";

/** The area-score file, or `null` when static files are off or it cannot be had. */
export function loadAreaScores(base: string | undefined = STATIC_URL): Promise<AreaScores | null> {
  return loadStaticPiece(base, "areaScores", decodeAreaScores);
}

/**
 * Every area's sub-scores from R2, once per page. `null` until loaded and for
 * good when `NEXT_PUBLIC_STATIC_URL` is unset or anything fails; callers then
 * keep using the API.
 */
export function useAreaScores(): AreaScores | null {
  const [areas, setAreas] = useState<AreaScores | null>(null);
  useEffect(() => {
    if (!STATIC_URL) return;
    let cancelled = false;
    void loadAreaScores().then((loaded) => {
      if (!cancelled) setAreas(loaded);
    });
    return () => {
      cancelled = true;
    };
  }, []);
  return areas;
}

/**
 * The PMTiles URL: `NEXT_PUBLIC_PMTILES_URL` when set, otherwise the
 * manifest's `tiles` entry once the manifest has loaded.
 */
export function useTilesUrl(): string | undefined {
  const [fromManifest, setFromManifest] = useState<string | undefined>();
  useEffect(() => {
    if (PMTILES_URL || !STATIC_URL) return;
    let cancelled = false;
    void loadStaticTilesUrl(STATIC_URL).then((url) => {
      if (!cancelled) setFromManifest(url);
    });
    return () => {
      cancelled = true;
    };
  }, []);
  return PMTILES_URL ?? fromManifest;
}
