"use client";

import { useMemo } from "react";

import type { ApiClient } from "@/lib/api/client";
import type { AreaGeometry, FactorKey } from "@/lib/api/types";
import {
  PER_FACTOR,
  keyPins,
  pinFactors,
  placeSearch,
  type KeyedPin,
} from "@/lib/map/placePins";

import { useDebouncedValue } from "./useDebouncedValue";
import { useResource } from "./useResource";

const NONE: KeyedPin[] = [];

/**
 * The places behind the selected place-based factors in and near a scored
 * area, for map pins. `point` is null when no result is showing. Pins are
 * empty while a new set loads and after any failure (best effort, no error
 * UI); a changed place or selection aborts the request it replaces.
 */
export function usePlacePins(
  point: { lat: number; lon: number } | null,
  geometry: AreaGeometry | null | undefined,
  selected: readonly FactorKey[],
  client: Pick<ApiClient, "getPlacesAround">,
): KeyedPin[] {
  const factors = useMemo(() => pinFactors(selected), [selected]);
  const factorsKey = factors.join(",");
  const debounced = useDebouncedValue(factors, factorsKey);
  const debouncedKey = debounced.join(",");

  const search = useMemo(
    () => (point ? placeSearch(point, geometry) : null),
    [point, geometry],
  );
  const key =
    search && debounced.length > 0
      ? `${search.lat},${search.lon},${search.radiusMi}|${debouncedKey}`
      : null;

  const resource = useResource(key, async (signal) => {
    const { lat, lon, radiusMi } = search as NonNullable<typeof search>;
    const result = await client.getPlacesAround(lat, lon, {
      factors: debounced,
      radiusMi,
      perFactor: PER_FACTOR,
      signal,
    });
    return keyPins(result.places);
  });

  // While the selection settles, the old pins would show factors that are
  // off; wait for the debounce so pins always match the pills.
  if (key === null || resource.status !== "ready" || debouncedKey !== factorsKey) {
    return NONE;
  }
  return resource.data ?? NONE;
}
