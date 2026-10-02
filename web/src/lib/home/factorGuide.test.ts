import { describe, expect, it } from "vitest";

import { ALL_FACTOR_KEYS, FACTOR_KEYS, FACTORS, UNDERLYING_FACTOR_KEYS } from "@/lib/score/factors";

import { FACTOR_GUIDE, MAX_FACTOR_WEIGHT } from "./factorGuide";

describe("factor guide", () => {
  it("has an entry for every factor and no extras", () => {
    expect(Object.keys(FACTOR_GUIDE).sort()).toEqual([...ALL_FACTOR_KEYS].sort());
  });

  it("flags exactly the underlying metrics", () => {
    expect(UNDERLYING_FACTOR_KEYS.sort()).toEqual(["premiumRetail", "trailPopularity"]);
    expect(FACTOR_KEYS).toHaveLength(12);
    for (const key of ALL_FACTOR_KEYS) {
      expect(Boolean(FACTOR_GUIDE[key].underlying), key).toBe(Boolean(FACTORS[key].underlying));
    }
  });

  it("gives every entry a weight and complete copy", () => {
    for (const [key, entry] of Object.entries(FACTOR_GUIDE)) {
      expect(entry.weight, key).toBeGreaterThan(0);
      for (const text of [entry.measures, entry.better, entry.why, entry.caveat]) {
        expect(text.trim().length, key).toBeGreaterThan(10);
      }
    }
    expect(MAX_FACTOR_WEIGHT).toBe(1.5);
  });

  it("matches the default weights in scoring/engine.py", () => {
    const weights = Object.fromEntries(
      Object.entries(FACTOR_GUIDE).map(([key, entry]) => [key, entry.weight]),
    );
    expect(weights).toEqual({
      grocery: 1.5,
      gym: 1.0,
      cafe: 1.0,
      restaurant: 1.0,
      bar: 0.5,
      premiumRetail: 0.75,
      gasStation: 1.0,
      convenienceStore: 0.75,
      transit: 1.5,
      school: 1.5,
      road: 1.0,
      emergencyCorridor: 0.75,
      airport: 0.75,
      trailPopularity: 1.25,
    });
  });

  it("explains the school 20/80 rule and the real emergency facilities", () => {
    expect(FACTOR_GUIDE.school.measures).toMatch(/20%/);
    expect(FACTOR_GUIDE.school.measures).toMatch(/80%/);
    expect(FACTOR_GUIDE.school.caveat).toMatch(/never zero/);
    expect(FACTOR_GUIDE.emergencyCorridor.measures).toMatch(
      /fire stations, hospitals and police stations/,
    );
    expect(FACTOR_GUIDE.emergencyCorridor.caveat).toMatch(/rough proxy/);
  });

  it("uses feet and miles, never metric", () => {
    for (const entry of Object.values(FACTOR_GUIDE)) {
      const text = `${entry.measures} ${entry.better} ${entry.why} ${entry.caveat}`;
      expect(text).not.toMatch(/\b\d[\d,.]*\s?(m|km|meters?|metres?|kilometers?)\b/i);
    }
  });
});
