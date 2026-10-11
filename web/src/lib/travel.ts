import type { ReachMode } from "@/lib/api/types";

/** 5, 10, 15 ... up to `max` minutes. */
function everyFive(max: number): readonly number[] {
  return Array.from({ length: max / 5 }, (_, i) => (i + 1) * 5);
}

/** Every mode steps by 5 minutes: walk and train 5-45, drive 5-60. */
export const TRAVEL_OPTIONS: ReadonlyArray<{
  mode: ReachMode;
  label: string;
  minutes: readonly number[];
  /** Minutes used when the user picks this mode. */
  initial: number;
}> = [
  { mode: "walk", label: "Walk", minutes: everyFive(45), initial: 10 },
  { mode: "transit", label: "Train", minutes: everyFive(45), initial: 20 },
  { mode: "drive", label: "Drive", minutes: everyFive(60), initial: 15 },
];

export function travelOption(mode: ReachMode) {
  return TRAVEL_OPTIONS.find((o) => o.mode === mode) ?? TRAVEL_OPTIONS[2];
}

/** Dense places (10k+ people per sq mi, "walk") start on a 20 min train; others drive 15. */
export function defaultTravel(travelMode: "walk" | "drive" | null | undefined): {
  mode: ReachMode;
  minutes: number;
} {
  return travelMode === "walk" ? { mode: "transit", minutes: 20 } : { mode: "drive", minutes: 15 };
}

/** Slower than the API's straight-line estimate on purpose: routed areas come out smaller. */
const TUNE_MPH: Record<ReachMode, number> = { walk: 3, transit: 10, drive: 22 };
const TUNE_CIRCUITY = 1.3;
/** Each area reaches a bit past the halfway point, so the overlap has room for some areas. */
const TUNE_REACH_SHARE = 0.7;
const TUNE_MIN_MINUTES = 10;

/** Miles a mode covers in `minutes`, as the tuner counts it. */
function tuneReachMi(mode: ReachMode, minutes: number): number {
  const moving = mode === "drive" ? minutes - 2 : minutes;
  return (Math.max(moving, 0) / 60) * TUNE_MPH[mode];
}

/**
 * One travel mode and the fewest minutes for the places' travel areas to overlap: walk when
 * the places are a short walk apart, then train where people here travel by train, else drive.
 * Null when they are too far apart for any mode.
 */
export function tuneTravel(
  places: readonly { lat: number; lon: number }[],
  travelMode: "walk" | "drive" | null | undefined,
): { mode: ReachMode; minutes: number } | null {
  let farthest = 0;
  for (let i = 0; i < places.length; i += 1) {
    for (let j = i + 1; j < places.length; j += 1) {
      farthest = Math.max(farthest, distanceMi(places[i], places[j]));
    }
  }
  const needMi = farthest * TUNE_CIRCUITY * TUNE_REACH_SHARE;
  const modes: ReachMode[] = travelMode === "walk" ? ["walk", "transit", "drive"] : ["walk", "drive"];
  for (const mode of modes) {
    const option = travelOption(mode);
    // Walking only while it stays a short walk; past that a faster mode is the honest answer.
    const cap = mode === "walk" ? 20 : option.minutes[option.minutes.length - 1];
    const minutes = option.minutes.find(
      (m) => m >= TUNE_MIN_MINUTES && m <= cap && tuneReachMi(mode, m) >= needMi,
    );
    if (minutes !== undefined) return { mode, minutes };
  }
  return null;
}

/** The next step up: more minutes, or a faster mode once the minutes run out. */
export function widerTravel(travel: { mode: ReachMode; minutes: number }): {
  mode: ReachMode;
  minutes: number;
} | null {
  const option = travelOption(travel.mode);
  const next = option.minutes.find((m) => m > travel.minutes);
  if (next !== undefined) return { mode: travel.mode, minutes: next };
  if (travel.mode === "walk") return { mode: "transit", minutes: 30 };
  if (travel.mode === "transit") return { mode: "drive", minutes: 30 };
  return null;
}

const EARTH_RADIUS_MI = 3958.8;

/** Great-circle miles between two points. */
export function distanceMi(
  a: { lat: number; lon: number },
  b: { lat: number; lon: number },
): number {
  const rad = Math.PI / 180;
  const dLat = (b.lat - a.lat) * rad;
  const dLon = (b.lon - a.lon) * rad;
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_MI * Math.asin(Math.min(1, Math.sqrt(h)));
}
