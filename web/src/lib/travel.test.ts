import { describe, expect, it } from "vitest";

import { defaultTravel, TRAVEL_OPTIONS, travelOption } from "./travel";

describe("defaultTravel", () => {
  it("starts dense places on a 20 min train", () => {
    expect(defaultTravel("walk")).toEqual({ mode: "transit", minutes: 20 });
  });
  it("drives 15 min everywhere else", () => {
    for (const m of ["drive", null, undefined] as const) {
      expect(defaultTravel(m)).toEqual({ mode: "drive", minutes: 15 });
    }
  });
});

describe("travel options", () => {
  it("keeps the per-mode ranges and initial minutes", () => {
    expect(TRAVEL_OPTIONS.map((o) => [o.mode, o.initial, o.minutes.at(-1)])).toEqual([
      ["walk", 10, 45],
      ["transit", 20, 45],
      ["drive", 15, 60],
    ]);
    expect(travelOption("transit").label).toBe("Train");
  });
});
