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

/** Slower than the API's straight-line estimate on purpose: routed areas come out smaller. */
const TUNE_MPH: Record<ReachMode, number> = { walk: 3, transit: 10, drive: 22 };
const TUNE_CIRCUITY = 1.3;
/** Two areas together reach this much past the road distance between their places, so the
 * overlap has room for some areas rather than touching at one point. */
const TUNE_OVERLAP = 1.4;

/** Miles a mode covers in `minutes`, as the tuner counts it. */
function tuneReachMi(travel: Travel): number {
  const moving = travel.mode === "drive" ? travel.minutes - 2 : travel.minutes;
  return (Math.max(moving, 0) / 60) * TUNE_MPH[travel.mode];
}

/** Faster modes in order: the train only where people here travel by train. */
function modeLadder(travelMode: "walk" | "drive" | null | undefined): ReachMode[] {
  return travelMode === "walk" ? ["walk", "transit", "drive"] : ["walk", "drive"];
}

/**
 * The next step up for one place: 5 more minutes, or once the mode's maximum is reached, the
 * next faster mode at the fewest minutes that reach at least as far. Null past a 60 min drive.
 */
export function widerTravel(
  travel: Travel,
  travelMode: "walk" | "drive" | null | undefined,
): Travel | null {
  const option = travelOption(travel.mode);
  const next = option.minutes.find((m) => m > travel.minutes);
  if (next !== undefined) return { mode: travel.mode, minutes: next };
  const ladder = modeLadder(travelMode);
  const reach = tuneReachMi(travel);
  for (const mode of ladder.slice(ladder.indexOf(travel.mode) + 1)) {
    const minutes = travelOption(mode).minutes.find(
      (m) => m >= DEFAULT_MINUTES && tuneReachMi({ mode, minutes: m }) > reach,
    );
    if (minutes !== undefined) return { mode, minutes };
  }
  return null;
}

/** The fewest steps up from `start` (never below it) that reach `needMi`; null if none do. */
function reachAtLeast(
  start: Travel,
  needMi: number,
  travelMode: "walk" | "drive" | null | undefined,
): Travel | null {
  let travel: Travel | null = start;
  while (travel && tuneReachMi(travel) < needMi) travel = widerTravel(travel, travelMode);
  return travel;
}

export interface TravelPlan {
  main: Travel;
  /** One per point of interest, in order. */
  pois: Travel[];
}

/**
 * Travel for the searched place and its points of interest so that their areas overlap. The
 * searched place is the one gone to most (work, say), so it keeps its own mode and minutes;
 * each point of interest starts there and gets only the extra time it needs (a grocery store
 * far out gets 25 min, not everyone), moving to a faster mode past its mode's maximum. When
 * the points of interest also miss each other, the one farther from the searched place gives
 * way. The searched place widens only when the points of interest cannot. Null when the places
 * are too far apart for any mode.
 */
export function tuneTravel(
  main: { lat: number; lon: number } & Travel,
  pois: readonly { lat: number; lon: number }[],
  travelMode: "walk" | "drive" | null | undefined,
): TravelPlan | null {
  const start: Travel = { mode: main.mode, minutes: main.minutes };
  const need = (a: { lat: number; lon: number }, b: { lat: number; lon: number }) =>
    distanceMi(a, b) * TUNE_CIRCUITY * TUNE_OVERLAP;
  let mainTravel: Travel | null = start;
  while (mainTravel) {
    const mainReach = tuneReachMi(mainTravel);
    const tuned = pois.map((poi) => reachAtLeast(start, need(main, poi) - mainReach, travelMode));
    if (tuned.every((t): t is Travel => t !== null)) {
      // Each point of interest now meets the searched place; make the two meet each other too.
      if (tuned.length === 2) {
        const far = distanceMi(main, pois[1]) > distanceMi(main, pois[0]) ? 1 : 0;
        const near = 1 - far;
        const farTravel = reachAtLeast(
          tuned[far],
          need(pois[0], pois[1]) - tuneReachMi(tuned[near]),
          travelMode,
        );
        if (farTravel) {
          tuned[far] = farTravel;
          return { main: mainTravel, pois: tuned };
        }
      } else {
        return { main: mainTravel, pois: tuned };
      }
    }
    mainTravel = widerTravel(mainTravel, travelMode);
  }
  return null;
}

/**
 * One step wider when the overlap came back empty: the point of interest farthest from the
 * searched place that can still widen, else the searched place. Null when nothing can.
 */
export function widenPlan(
  plan: TravelPlan,
  main: { lat: number; lon: number },
  pois: readonly { lat: number; lon: number }[],
  travelMode: "walk" | "drive" | null | undefined,
): TravelPlan | null {
  const order = pois
    .map((poi, i) => ({ i, d: distanceMi(main, poi) }))
    .sort((a, b) => b.d - a.d);
  for (const { i } of order) {
    const wider = plan.pois[i] ? widerTravel(plan.pois[i], travelMode) : null;
    if (wider) return { main: plan.main, pois: plan.pois.map((t, j) => (j === i ? wider : t)) };
  }
  const wider = widerTravel(plan.main, travelMode);
  return wider ? { main: wider, pois: plan.pois } : null;
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
