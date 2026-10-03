import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { PILL_RAMP_STOPS, scorePillColor } from "./pillColors";

const css = readFileSync(join(__dirname, "../../app/globals.css"), "utf8");

/** Token values from the first `--name` run found after `marker` in globals.css. */
function tokens(marker: string): Record<string, string> {
  const start = css.indexOf(marker);
  const end = css.indexOf("}", start);
  const out: Record<string, string> = {};
  for (const m of css.slice(start, end).matchAll(/(--[\w-]+):\s*([^;]+);/g)) {
    out[m[1]] = m[2].trim();
  }
  return out;
}

const THEMES = {
  light: tokens(":root {"),
  dark: tokens(':root[data-theme="dark"]'),
  osDark: tokens(':root:not([data-theme="light"])'),
};

function rgb(hex: string): [number, number, number] {
  const n = Number.parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function luminance(c: number[]): number {
  const [r, g, b] = c.map((v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: number[], b: number[]): number {
  const [x, y] = [luminance(a), luminance(b)];
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}

function hue([r, g, b]: number[]): number {
  const max = Math.max(r, g, b);
  const d = max - Math.min(r, g, b);
  if (d === 0) return 0;
  const h =
    max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return (h * 60 + 360) % 360;
}

describe("scorePillColor", () => {
  it("returns the end stops as variables and clamps out-of-range scores", () => {
    expect(scorePillColor(0)).toBe("var(--score-0)");
    expect(scorePillColor(100)).toBe("var(--score-100)");
    expect(scorePillColor(-20)).toBe(scorePillColor(0));
    expect(scorePillColor(250)).toBe(scorePillColor(100));
  });

  it("treats NaN and infinities safely", () => {
    expect(scorePillColor(Number.NaN)).toBe("var(--score-0)");
    expect(scorePillColor(Number.POSITIVE_INFINITY)).toBe(scorePillColor(0));
  });

  it("returns an exact variable on every stop and blends between them", () => {
    for (const [score, name] of PILL_RAMP_STOPS) {
      expect(scorePillColor(score)).toBe(`var(${name})`);
    }
    expect(scorePillColor(45)).toBe(
      "color-mix(in srgb, var(--score-55) 50%, var(--score-35))",
    );
    expect(scorePillColor(87.5)).toBe(
      "color-mix(in srgb, var(--score-100) 50%, var(--score-75))",
    );
  });
});

describe.each(Object.entries(THEMES))("ramp tokens (%s)", (theme, vars) => {
  const colors = PILL_RAMP_STOPS.map(([, name]) => vars[name]);

  it("defines every stop as a hex colour", () => {
    for (const c of colors) expect(c).toMatch(/^#[0-9a-f]{6}$/i);
  });

  it("runs from red through yellow to green (hue rises monotonically)", () => {
    const hues = colors.map((c) => hue(rgb(c)));
    for (let i = 1; i < hues.length; i++) expect(hues[i]).toBeGreaterThan(hues[i - 1]);
    expect(hues[0]).toBeLessThan(15);
    expect(hues[hues.length - 1]).toBeGreaterThan(110);
  });

  it("keeps the arc at >= 3:1 against the pill backgrounds", () => {
    const surface = rgb(vars["--surface"]);
    const sunken = rgb(vars["--surface-sunken"]);
    const accent = rgb(vars["--accent"]);
    // The selected pill tints the surface with 16% accent.
    const tinted = surface.map((c, i) => Math.round(c * 0.84 + accent[i] * 0.16));
    for (const c of colors) {
      for (const bg of [surface, sunken, tinted]) {
        expect(contrast(rgb(c), bg)).toBeGreaterThanOrEqual(3);
      }
    }
  });
});
