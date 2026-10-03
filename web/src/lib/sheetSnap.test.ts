import { describe, expect, it } from "vitest";

import {
  clampOffset,
  cycleSnap,
  nearestSnap,
  releaseVelocity,
  resolveSnap,
  snapOffsets,
  stepSnap,
} from "./sheetSnap";

const offsets = snapOffsets(800, 100); // full 0, half 400, peek 700

describe("snapOffsets", () => {
  it("places full at the top, half in the middle and peek leaving the peek height", () => {
    expect(offsets).toEqual({ full: 0, half: 400, peek: 700 });
  });

  it("never lets half sit lower than peek on a tiny sheet", () => {
    expect(snapOffsets(150, 100)).toEqual({ full: 0, half: 50, peek: 50 });
    expect(snapOffsets(0, 100)).toEqual({ full: 0, half: 0, peek: 0 });
  });
});

describe("clampOffset", () => {
  it("limits a drag to the sheet's travel", () => {
    expect(clampOffset(-30, offsets)).toBe(0);
    expect(clampOffset(300, offsets)).toBe(300);
    expect(clampOffset(900, offsets)).toBe(700);
  });
});

describe("releaseVelocity", () => {
  it("is zero without movement or samples", () => {
    expect(releaseVelocity([])).toBe(0);
    expect(releaseVelocity([{ time: 5, y: 10 }])).toBe(0);
  });

  it("is positive moving down and negative moving up", () => {
    expect(
      releaseVelocity([
        { time: 0, y: 0 },
        { time: 50, y: 25 },
      ]),
    ).toBeCloseTo(0.5);
    expect(
      releaseVelocity([
        { time: 0, y: 100 },
        { time: 50, y: 50 },
      ]),
    ).toBeCloseTo(-1);
  });

  it("ignores samples older than the window", () => {
    expect(
      releaseVelocity([
        { time: 0, y: 0 },
        { time: 500, y: 300 },
        { time: 550, y: 300 },
      ]),
    ).toBe(0);
  });
});

describe("nearestSnap", () => {
  it("picks the closest snap", () => {
    expect(nearestSnap(100, offsets)).toBe("full");
    expect(nearestSnap(250, offsets)).toBe("half");
    expect(nearestSnap(560, offsets)).toBe("peek");
    expect(nearestSnap(900, offsets)).toBe("peek");
  });
});

describe("stepSnap and cycleSnap", () => {
  it("steps one snap and stops at the ends", () => {
    expect(stepSnap("peek", "up")).toBe("half");
    expect(stepSnap("half", "up")).toBe("full");
    expect(stepSnap("full", "up")).toBe("full");
    expect(stepSnap("full", "down")).toBe("half");
    expect(stepSnap("peek", "down")).toBe("peek");
  });

  it("cycles peek, half, full, peek", () => {
    expect(cycleSnap("peek")).toBe("half");
    expect(cycleSnap("half")).toBe("full");
    expect(cycleSnap("full")).toBe("peek");
  });
});

describe("resolveSnap", () => {
  it("settles a slow drag on the nearest snap", () => {
    expect(
      resolveSnap({ offset: 450, velocity: 0.05, offsets, current: "peek" }),
    ).toBe("half");
    expect(
      resolveSnap({ offset: 600, velocity: -0.1, offsets, current: "half" }),
    ).toBe("peek");
  });

  it("lets a small nudge fall back to where it started", () => {
    expect(
      resolveSnap({ offset: 380, velocity: 0.1, offsets, current: "half" }),
    ).toBe("half");
  });

  it("projects a flick past the nearest snap", () => {
    // Released near half but flung upwards hard: lands on full.
    expect(
      resolveSnap({ offset: 330, velocity: -1.5, offsets, current: "half" }),
    ).toBe("full");
    // Flung down from half all the way.
    expect(
      resolveSnap({ offset: 450, velocity: 2, offsets, current: "half" }),
    ).toBe("peek");
  });

  it("moves at least one snap in the direction of a flick", () => {
    expect(
      resolveSnap({ offset: 690, velocity: -0.5, offsets, current: "peek" }),
    ).toBe("half");
    expect(
      resolveSnap({ offset: 10, velocity: 0.5, offsets, current: "full" }),
    ).toBe("half");
  });

  it("cannot flick beyond the ends", () => {
    expect(
      resolveSnap({ offset: 5, velocity: -3, offsets, current: "full" }),
    ).toBe("full");
    expect(
      resolveSnap({ offset: 695, velocity: 3, offsets, current: "peek" }),
    ).toBe("peek");
  });
});
