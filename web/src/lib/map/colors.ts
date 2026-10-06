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

/** The dark basemap swallows the low end of the ramp, so cells are more opaque on it. */
export const CELL_OPACITY = { light: 0.6, dark: 0.55 } as const;

/** The clicked secondary-road area: a tint, an accent outline and a contrasting casing. */
export const AREA_STYLE = {
  light: { fillOpacity: 0.12, line: "#1d4ed8", casing: "#ffffff" },
  dark: { fillOpacity: 0.18, line: "#93c5fd", casing: "#0b1020" },
} as const;

/** A previewed (not selected) area: dashed orange, distinct from the blue selection. */
export const PREVIEW_STYLE = {
  light: { fillOpacity: 0.14, line: "#c2410c", casing: "#ffffff" },
  dark: { fillOpacity: 0.2, line: "#fdba74", casing: "#0b1020" },
} as const;

/**
 * The reachable-area overlay (isochrone): magenta, a hue the score ramp never uses, so the
 * outline stands out over any cell colour (it was teal and vanished into the green cells).
 * Distinct from the blue selection and orange preview.
 */
export const REACH_STYLE = {
  light: { fillOpacity: 0.12, line: "#c026d3", casing: "#ffffff" },
  dark: { fillOpacity: 0.18, line: "#f0abfc", casing: "#0b1020" },
} as const;

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
