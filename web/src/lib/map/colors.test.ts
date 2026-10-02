import { describe, expect, it } from "vitest";

import { FILL_COLOR_EXPRESSION, RAMP_STOPS, scoreColor } from "./colors";

describe("color ramp", () => {
  it("runs from 0 to 100 in ascending stops, as MapLibre requires", () => {
    const scores = RAMP_STOPS.map(([score]) => score);
    expect(scores[0]).toBe(0);
    expect(scores.at(-1)).toBe(100);
    expect([...scores].sort((a, b) => a - b)).toEqual(scores);
  });

  it("feeds the same stops to the map layer expression", () => {
    expect(FILL_COLOR_EXPRESSION.slice(0, 3)).toEqual([
      "interpolate",
      ["linear"],
      ["get", "score"],
    ]);
    expect(FILL_COLOR_EXPRESSION.slice(3)).toEqual(RAMP_STOPS.flat());
  });

  it("gets lighter as the score rises, so it reads in greyscale", () => {
    const luminance = (rgb: string) => {
      const [r, g, b] = rgb.match(/\d+/g)!.map(Number);
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    const values = [0, 20, 40, 60, 80, 100].map((s) =>
      luminance(scoreColor(s)),
    );
    expect([...values].sort((a, b) => a - b)).toEqual(values);
  });

  it("returns the stop colors exactly at the stops and clamps outside", () => {
    expect(scoreColor(0)).toBe("rgb(68 1 84)");
    expect(scoreColor(100)).toBe("rgb(253 231 37)");
    expect(scoreColor(-20)).toBe(scoreColor(0));
    expect(scoreColor(250)).toBe(scoreColor(100));
  });
});
