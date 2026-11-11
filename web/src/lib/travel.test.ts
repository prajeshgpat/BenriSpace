import { describe, expect, it } from "vitest";

import {
  defaultTravel,
  distanceMi,
  TRAVEL_OPTIONS,
  travelOption,
} from "./travel";

describe("defaultTravel", () => {
  it("starts dense places on a 10 min train", () => {
    expect(defaultTravel("walk")).toEqual({ mode: "transit", minutes: 10 });
  });
  it("drives 10 min everywhere else", () => {
    for (const m of ["drive", null, undefined] as const) {
      expect(defaultTravel(m)).toEqual({ mode: "drive", minutes: 10 });
    }
  });
});

describe("travel options", () => {
  it("starts every mode at 10 min and caps walk 30, train 45, drive 60", () => {
    expect(TRAVEL_OPTIONS.map((o) => [o.mode, o.initial, o.minutes[0], o.minutes.at(-1)])).toEqual([
      ["walk", 10, 5, 30],
      ["transit", 10, 5, 45],
      ["drive", 10, 5, 60],
    ]);
    expect(travelOption("transit").label).toBe("Train");
  });
});

describe("distanceMi", () => {
  it("is zero for the same point and about 69 mi per degree of latitude", () => {
    expect(distanceMi({ lat: 40, lon: -74 }, { lat: 40, lon: -74 })).toBe(0);
    expect(distanceMi({ lat: 40, lon: -74 }, { lat: 41, lon: -74 })).toBeCloseTo(69, 0);
  });
});
