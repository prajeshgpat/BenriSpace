import { describe, expect, it } from "vitest";

import {
  buildTriangulateRequest,
  clampMinutes,
  formatTravelLine,
  freezeMinutes,
  shortLabel,
  shownMinutes,
  type TunePlace,
} from "./tripTune";

const places: TunePlace[] = [
  { label: "Work", lat: 40.7, lon: -74, mode: "transit", minutes: 10, tripsPerWeek: 5 },
  { label: "Gym", lat: 40.8, lon: -73.9, mode: "walk", minutes: 20, tripsPerWeek: 2 },
];

describe("buildTriangulateRequest", () => {
  it("auto sends each mode and frequency and no minutes", () => {
    const { anchors, tune } = buildTriangulateRequest(places, "auto");
    expect(tune).toBe("auto");
    expect(anchors).toEqual([
      { label: "Work", lat: 40.7, lon: -74, mode: "transit", tripsPerWeek: 5 },
      { label: "Gym", lat: 40.8, lon: -73.9, mode: "walk", tripsPerWeek: 2 },
    ]);
    expect(anchors.every((a) => !("minutes" in a))).toBe(true);
  });

  it("fixed sends the minutes as shown", () => {
    const { anchors, tune } = buildTriangulateRequest(places, "fixed");
    expect(tune).toBe("fixed");
    expect(anchors.map((a) => a.minutes)).toEqual([10, 20]);
  });
});

describe("minutes", () => {
  it("shows the tuned minutes in auto once known, else the place's own", () => {
    expect(shownMinutes("auto", 15, 10)).toBe(15);
    expect(shownMinutes("auto", null, 10)).toBe(10);
    expect(shownMinutes("fixed", 15, 10)).toBe(10);
  });

  it("clamps to the mode's stepper range", () => {
    expect(clampMinutes("walk", 45)).toBe(30);
    expect(clampMinutes("transit", 45)).toBe(45);
    expect(clampMinutes("drive", 2)).toBe(5);
  });

  it("freezes a place at the tuned minutes, within its mode's range", () => {
    expect(freezeMinutes("drive", 15, 10)).toBe(15);
    expect(freezeMinutes("walk", 45, 10)).toBe(30);
    expect(freezeMinutes("walk", null, 10)).toBe(10);
  });
});

describe("result travel text", () => {
  const travel = [
    { label: "Work", mode: "walk" as const, minutes: 5 },
    { label: "The Gym, 5 Main St", mode: "transit" as const, minutes: 15 },
  ];
  it("writes one-way minutes with mode words", () => {
    expect(formatTravelLine(travel)).toBe("Work 5 min walk · The Gym 15 min train");
    expect(formatTravelLine([{ label: "Mall", mode: "drive", minutes: 8 }])).toBe("Mall 8 min drive");
    expect(formatTravelLine([])).toBe("");
  });
  it("shortens addresses at the first comma", () => {
    expect(shortLabel("350 5th Ave, New York, NY")).toBe("350 5th Ave");
    expect(shortLabel("Home")).toBe("Home");
  });
});
