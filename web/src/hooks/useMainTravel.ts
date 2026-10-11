"use client";

import { useCallback, useState } from "react";

import type { ReachMode } from "@/lib/api/types";
import { defaultTravel } from "@/lib/travel";

export interface MainTravel {
  mode: ReachMode;
  minutes: number;
  /** The user (or the overlap tuner) picked this; the place's default no longer applies. */
  chosen: boolean;
  set: (mode: ReachMode, minutes: number) => void;
}

/**
 * The searched place's travel mode and minutes, which the points of interest follow unless
 * set apart. Until something is picked, the mode follows the place (a 20 min train in dense
 * places, a 15 min drive elsewhere).
 */
export function useMainTravel(travelMode: "walk" | "drive" | null | undefined): MainTravel {
  const placeDefault = defaultTravel(travelMode);
  const placeKey = travelMode === "walk" ? "walk" : "drive";
  const [chosen, setChosen] = useState(false);
  const [mode, setMode] = useState<ReachMode>(placeDefault.mode);
  const [minutes, setMinutes] = useState(placeDefault.minutes);
  const [seenPlaceKey, setSeenPlaceKey] = useState(placeKey);
  if (travelMode && seenPlaceKey !== placeKey) {
    setSeenPlaceKey(placeKey);
    if (!chosen) {
      setMode(placeDefault.mode);
      setMinutes(placeDefault.minutes);
    }
  }
  const set = useCallback((nextMode: ReachMode, nextMinutes: number) => {
    setChosen(true);
    setMode(nextMode);
    setMinutes(nextMinutes);
  }, []);
  return { mode, minutes, chosen, set };
}
