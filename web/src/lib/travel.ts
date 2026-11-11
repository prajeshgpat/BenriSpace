import type { ReachMode } from "@/lib/api/types";

export interface Travel {
  mode: ReachMode;
  minutes: number;
}

/** The point of the site: what is within 10 minutes. Every mode starts there. */
export const DEFAULT_MINUTES = 10;

/** 5, 10, 15 ... up to `max` minutes. */
function everyFive(max: number): readonly number[] {
  return Array.from({ length: max / 5 }, (_, i) => (i + 1) * 5);
}

/** Every mode steps by 5 minutes: walk 5-30, train 5-45, drive 5-60. */
export const TRAVEL_OPTIONS: ReadonlyArray<{
  mode: ReachMode;
  label: string;
  minutes: readonly number[];
  /** Minutes used when the user picks this mode. */
  initial: number;
}> = [
  { mode: "walk", label: "Walk", minutes: everyFive(30), initial: DEFAULT_MINUTES },
  { mode: "transit", label: "Train", minutes: everyFive(45), initial: DEFAULT_MINUTES },
  { mode: "drive", label: "Drive", minutes: everyFive(60), initial: DEFAULT_MINUTES },
];

export function travelOption(mode: ReachMode) {
  return TRAVEL_OPTIONS.find((o) => o.mode === mode) ?? TRAVEL_OPTIONS[2];
}

/** Dense places (10k+ people per sq mi, "walk") start on a 10 min train; others drive 10. */
export function defaultTravel(travelMode: "walk" | "drive" | null | undefined): Travel {
  return { mode: travelMode === "walk" ? "transit" : "drive", minutes: DEFAULT_MINUTES };
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
