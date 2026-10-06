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
