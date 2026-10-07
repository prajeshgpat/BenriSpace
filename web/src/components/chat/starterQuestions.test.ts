import { describe, expect, it } from "vitest";

import { FACTOR_KEYS } from "@/lib/score/factors";

import { starterQuestions } from "./starterQuestions";

const MULTI = "Find a neighborhood near my work, a Trader Joe's and a Planet Fitness";

describe("starterQuestions", () => {
  it("uses the first three factors when everything is on", () => {
    expect(starterQuestions(undefined, true)).toEqual([
      "Is it good for groceries and restaurants?",
      "Is there a good cafe within walking distance?",
      MULTI,
    ]);
    expect(starterQuestions(FACTOR_KEYS, false)).toEqual([
      "Which neighborhoods are best for groceries and restaurants?",
      "Which areas have the best cafes?",
      MULTI,
    ]);
  });

  it("leads with the overlap question when places are being compared", () => {
    expect(starterQuestions(undefined, true, true)).toEqual([
      "What are the pros and cons of the areas in the overlap?",
      "Is it good for groceries and restaurants?",
      "Is there a good cafe within walking distance?",
    ]);
  });

  it("follows the selected factors in display order", () => {
    expect(starterQuestions(["recreation", "transit", "grocery", "airport"], true)).toEqual([
      "Is it good for groceries and transit?",
      "How long is the trip to the airport?",
      MULTI,
    ]);
    expect(starterQuestions(["recreation", "transit", "grocery"], true)[1]).toBe("Are there parks close by?");
  });

  it("falls back to generic questions with nothing selected", () => {
    expect(starterQuestions([], true)).toEqual([
      "What are the best things about this area?",
      "Find a quieter area near here",
      MULTI,
    ]);
    expect(starterQuestions([], false)[0]).toBe("Which neighborhoods score best overall?");
  });

  it("fills the slots without repeating for one or two factors", () => {
    const one = starterQuestions(["gym"], true);
    expect(one).toEqual(["Is there a gym close by?", "Find a quieter area near here", MULTI]);
    const two = starterQuestions(["cafe", "transit"], false);
    expect(two).toEqual([
      "Which neighborhoods are best for cafes and transit?",
      "Which areas have the best transit?",
      MULTI,
    ]);
    for (const set of [one, two]) expect(new Set(set).size).toBe(3);
  });

  it("always returns three questions", () => {
    for (let n = 0; n <= FACTOR_KEYS.length; n += 1) {
      for (const hasPlace of [true, false]) {
        expect(starterQuestions(FACTOR_KEYS.slice(0, n), hasPlace)).toHaveLength(3);
      }
    }
  });
});
