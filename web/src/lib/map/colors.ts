import { SCORE_MAX, clampScore } from "@/lib/score/presentation";

/**
 * Viridis, sampled at quartiles. It is perceptually uniform and readable with
 * the common forms of colour-vision deficiency, and its lightness rises
 * monotonically, so "higher is better" survives greyscale too.
 */
export const RAMP_STOPS: ReadonlyArray<
  readonly [score: number, color: string]
> = [
  [0, "#440154"],
  [25, "#3b528b"],
  [50, "#21918c"],
  [75, "#5ec962"],
  [100, "#fde725"],
];

export const CELL_OPACITY = 0.6;

export const RAMP_GRADIENT = `linear-gradient(to right, ${RAMP_STOPS.map(
  ([score, color]) => `${color} ${(score / SCORE_MAX) * 100}%`,
).join(", ")})`;

/** MapLibre expression coloring a feature by its `score` property. */
export const FILL_COLOR_EXPRESSION = [
  "interpolate",
  ["linear"],
  ["get", "score"],
  ...RAMP_STOPS.flat(),
];

function hexToRgb(hex: string): [number, number, number] {
  const n = Number.parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/** The ramp color for a score, matching the map layer; used for swatches. */
export function scoreColor(score: number): string {
  const value = clampScore(score);
  for (let i = 1; i < RAMP_STOPS.length; i++) {
    const [hi, hiColor] = RAMP_STOPS[i];
    if (value <= hi) {
      const [lo, loColor] = RAMP_STOPS[i - 1];
      const t = (value - lo) / (hi - lo);
      const a = hexToRgb(loColor);
      const b = hexToRgb(hiColor);
      const [r, g, bl] = a.map((c, k) => Math.round(c + (b[k] - c) * t));
      return `rgb(${r} ${g} ${bl})`;
    }
  }
  return RAMP_STOPS[RAMP_STOPS.length - 1][1];
}
