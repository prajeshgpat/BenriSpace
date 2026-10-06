"use client";

import { useCallback, useEffect, useState } from "react";

import {
  MAX_COMPARE,
  addPlace,
  loadPlaces,
  pinWithCurrent,
  removePlace,
  savePlaces,
  type ComparePlace,
} from "@/lib/compare";

/** Up to four pinned places, kept in sessionStorage for the tab. */
export function useCompare() {
  const [places, setPlaces] = useState<ComparePlace[]>([]);
  const [hydrated, setHydrated] = useState(false);

  // sessionStorage only exists in the browser; read it after mount.
  useEffect(() => {
    setPlaces(loadPlaces());
    setHydrated(true);
  }, []);
  useEffect(() => {
    if (hydrated) savePlaces(places);
  }, [places, hydrated]);

  const add = useCallback(
    (place: ComparePlace) => setPlaces((current) => addPlace(current, place)),
    [],
  );
  const remove = useCallback(
    (id: string) => setPlaces((current) => removePlace(current, id)),
    [],
  );
  const clear = useCallback(() => setPlaces([]), []);
  const toggle = useCallback(
    (place: ComparePlace, companion?: ComparePlace) =>
      setPlaces((current) => pinWithCurrent(current, place, companion)),
    [],
  );
  return { places, add, remove, clear, toggle, full: places.length >= MAX_COMPARE };
}

export type CompareState = ReturnType<typeof useCompare>;
