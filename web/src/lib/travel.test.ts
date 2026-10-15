import { describe, expect, it } from "vitest";

import {
  defaultTravel,
  distanceMi,
  TRAVEL_OPTIONS,
  travelOption,
  tuneTravel,
  widenPlan,
  widerTravel,
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

// Points about `miles` north (positive) or south (negative) of A.
const A = { lat: 40.75, lon: -73.99 };
const at = (miles: number) => ({ lat: A.lat + miles / 69, lon: A.lon });
const drive10 = { ...A, mode: "drive" as const, minutes: 10 };
const train10 = { ...A, mode: "transit" as const, minutes: 10 };

describe("tuneTravel", () => {
  it("keeps everyone at 10 min when a point of interest is close", () => {
    expect(distanceMi(A, at(2))).toBeCloseTo(2, 1);
    expect(tuneTravel(drive10, [at(2)], "drive")).toEqual({
      main: { mode: "drive", minutes: 10 },
      pois: [{ mode: "drive", minutes: 10 }],
    });
  });

  it("gives a far point of interest more time and leaves the searched place at 10", () => {
    const plan = tuneTravel(drive10, [at(6)], "drive")!;
    expect(plan.main).toEqual({ mode: "drive", minutes: 10 });
    expect(plan.pois).toEqual([{ mode: "drive", minutes: 25 }]);
  });

  it("raises only the point of interest that is far out", () => {
    const plan = tuneTravel(drive10, [at(1), at(-4)], "drive")!;
    expect(plan.main).toEqual({ mode: "drive", minutes: 10 });
    expect(plan.pois[0]).toEqual({ mode: "drive", minutes: 10 });
    // 15 min would meet the searched place; 20 also meets the near point of interest.
    expect(plan.pois[1]).toEqual({ mode: "drive", minutes: 20 });
  });

  it("keeps the searched place's train and steps up its minutes in a dense place", () => {
    const plan = tuneTravel(train10, [at(5)], "walk")!;
    expect(plan.main).toEqual({ mode: "transit", minutes: 10 });
    expect(plan.pois).toEqual([{ mode: "transit", minutes: 45 }]);
  });

  it("moves to driving once a train would pass its 45 min maximum", () => {
    const plan = tuneTravel(train10, [at(6)], "walk")!;
    expect(plan.main).toEqual({ mode: "transit", minutes: 10 });
    expect(plan.pois).toEqual([{ mode: "drive", minutes: 30 }]);
  });

  it("follows a mode the user picked for the searched place", () => {
    const plan = tuneTravel({ ...A, mode: "walk", minutes: 10 }, [at(0.5)], "drive")!;
    expect(plan).toEqual({ main: { mode: "walk", minutes: 10 }, pois: [{ mode: "walk", minutes: 10 }] });
  });

  it("gives null when the places are too far apart", () => {
    expect(tuneTravel(drive10, [at(150)], "drive")).toBeNull();
    expect(tuneTravel(train10, [at(150)], "walk")).toBeNull();
  });
});

describe("widerTravel", () => {
  it("steps minutes up by 5 within the mode", () => {
    expect(widerTravel({ mode: "walk", minutes: 10 }, "walk")).toEqual({ mode: "walk", minutes: 15 });
    expect(widerTravel({ mode: "drive", minutes: 55 }, "drive")).toEqual({ mode: "drive", minutes: 60 });
  });

  it("moves to the next faster mode past the maximum, reaching at least as far", () => {
    expect(widerTravel({ mode: "walk", minutes: 30 }, "walk")).toEqual({ mode: "transit", minutes: 10 });
    expect(widerTravel({ mode: "walk", minutes: 30 }, "drive")).toEqual({ mode: "drive", minutes: 10 });
    expect(widerTravel({ mode: "transit", minutes: 45 }, "walk")).toEqual({ mode: "drive", minutes: 25 });
  });

  it("has no step past a 60 min drive", () => {
    expect(widerTravel({ mode: "drive", minutes: 60 }, "drive")).toBeNull();
  });
});

describe("widenPlan", () => {
  it("widens the point of interest farthest from the searched place first", () => {
    const plan = {
      main: { mode: "drive" as const, minutes: 10 },
      pois: [
        { mode: "drive" as const, minutes: 10 },
        { mode: "drive" as const, minutes: 20 },
      ],
    };
    expect(widenPlan(plan, A, [at(1), at(-4)], "drive")).toEqual({
      main: plan.main,
      pois: [plan.pois[0], { mode: "drive", minutes: 25 }],
    });
  });

  it("widens the searched place only when no point of interest can", () => {
    const plan = {
      main: { mode: "drive" as const, minutes: 10 },
      pois: [{ mode: "drive" as const, minutes: 60 }],
    };
    expect(widenPlan(plan, A, [at(20)], "drive")).toEqual({
      main: { mode: "drive", minutes: 15 },
      pois: plan.pois,
    });
  });
});

describe("distanceMi", () => {
  it("is zero for the same point and about 69 mi per degree of latitude", () => {
    expect(distanceMi({ lat: 40, lon: -74 }, { lat: 40, lon: -74 })).toBe(0);
    expect(distanceMi({ lat: 40, lon: -74 }, { lat: 41, lon: -74 })).toBeCloseTo(69, 0);
  });
});
