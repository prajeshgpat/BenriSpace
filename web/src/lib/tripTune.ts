import type { AnchorTravel, ReachMode, TriangulateAnchor, TriangulateTune } from "@/lib/api/types";
import { travelOption } from "@/lib/travel";

/** One-way trips per week to a place, as the "How often" control offers them. */
export const TRIPS_PER_WEEK_OPTIONS = [
  { value: 5, label: "Daily" },
  { value: 2, label: "Few times a week" },
  { value: 1, label: "Weekly" },
] as const;

/** The searched place (home base, e.g. work) is always gone to daily. */
export const MAIN_TRIPS_PER_WEEK = 5;
/** A point of interest is gone to a few times a week until the user says otherwise. */
export const DEFAULT_POI_TRIPS_PER_WEEK = 2;

/** A place with the travel the user picked for it (used as given only in fixed mode). */
export interface TunePlace {
  label: string;
  lat: number;
  lon: number;
  mode: ReachMode;
  minutes: number;
  tripsPerWeek: number;
}

/**
 * The `POST /triangulate` request. Auto sends each place's mode and frequency and no minutes
 * (the server finds the fewest that overlap); fixed sends the minutes as shown.
 */
export function buildTriangulateRequest(
  places: readonly TunePlace[],
  tune: TriangulateTune,
): { anchors: TriangulateAnchor[]; tune: TriangulateTune } {
  const anchors = places.map<TriangulateAnchor>((p) =>
    tune === "auto"
      ? { label: p.label, lat: p.lat, lon: p.lon, mode: p.mode, tripsPerWeek: p.tripsPerWeek }
      : { label: p.label, lat: p.lat, lon: p.lon, mode: p.mode, minutes: p.minutes },
  );
  return { anchors, tune };
}

/** The most minutes the mode's stepper offers. */
export function clampMinutes(mode: ReachMode, minutes: number): number {
  const options = travelOption(mode).minutes;
  return Math.min(Math.max(minutes, options[0]), options[options.length - 1]);
}

/**
 * The minutes a badge shows: what the server tuned to while fitting automatically (once
 * known), otherwise the place's own minutes.
 */
export function shownMinutes(
  tune: TriangulateTune,
  tunedMinutes: number | null,
  ownMinutes: number,
): number {
  return tune === "auto" && tunedMinutes !== null ? tunedMinutes : ownMinutes;
}

/**
 * Minutes to freeze a place at when the user takes over from automatic fitting: what is shown
 * now, kept within the mode's stepper range.
 */
export function freezeMinutes(
  mode: ReachMode,
  tunedMinutes: number | null,
  ownMinutes: number,
): number {
  return clampMinutes(mode, tunedMinutes ?? ownMinutes);
}

const MODE_WORD: Record<ReachMode, string> = { walk: "walk", transit: "train", drive: "drive" };

/** A place's short name: its label up to the first comma ("350 5th Ave, New York" -> "350 5th Ave"). */
export function shortLabel(label: string): string {
  const first = label.split(",")[0]?.trim();
  return first ? first : label;
}

/** "Work 5 min walk · Gym 15 min train": one-way, per place, in the daily sense. */
export function formatTravelLine(travel: readonly AnchorTravel[]): string {
  return travel.map((t) => `${shortLabel(t.label)} ${t.minutes} min ${MODE_WORD[t.mode]}`).join(" · ");
}
