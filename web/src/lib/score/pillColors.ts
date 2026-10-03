import { clampScore } from "@/lib/score/presentation";

/**
 * Quality ramp (red -> orange -> yellow -> green) for the score rings in the
 * filter pills and the result header. It is deliberately separate from the
 * map's viridis ramp: on the map, colour encodes position on a continuous
 * scale; here it reads as "good / not good". The number is always printed
 * next to the ring, so colour is never the only signal.
 *
 * The stop colours live in globals.css (--score-0 ... --score-100) with
 * separate light and dark values, each tuned for >= 3:1 against the pill
 * backgrounds in its theme. This function returns CSS (var + color-mix), so
 * it works during SSR and in tests, and follows the theme without any JS.
 */
export const PILL_RAMP_STOPS: ReadonlyArray<
  readonly [score: number, variable: string]
> = [
  [0, "--score-0"],
  [35, "--score-35"],
  [55, "--score-55"],
  [75, "--score-75"],
  [100, "--score-100"],
];

export function scorePillColor(score: number): string {
  const value = clampScore(Number.isFinite(score) ? score : 0);
  for (let i = 0; i < PILL_RAMP_STOPS.length; i++) {
    const [at, name] = PILL_RAMP_STOPS[i];
    if (value === at) return `var(${name})`;
    if (value < at) {
      const [lo, loName] = PILL_RAMP_STOPS[i - 1];
      const t = Math.round(((value - lo) / (at - lo)) * 100);
      return `color-mix(in srgb, var(${name}) ${t}%, var(${loName}))`;
    }
  }
  return `var(${PILL_RAMP_STOPS[PILL_RAMP_STOPS.length - 1][1]})`;
}

