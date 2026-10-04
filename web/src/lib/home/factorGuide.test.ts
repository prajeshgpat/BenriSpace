import { describe, expect, it } from "vitest";

import { ALL_FACTOR_KEYS, FACTOR_KEYS } from "@/lib/score/factors";

import { FACTOR_GUIDE, MAX_FACTOR_WEIGHT } from "./factorGuide";

describe("factor guide", () => {
  it("has an entry for every factor and no extras", () => {
    expect(Object.keys(FACTOR_GUIDE).sort()).toEqual([...ALL_FACTOR_KEYS].sort());
  });

  it("has thirteen user-facing factors and no hidden ones", () => {
    expect(FACTOR_KEYS).toHaveLength(13);
    expect(ALL_FACTOR_KEYS).toEqual(FACTOR_KEYS);
  });

  it("gives every entry a weight and complete copy", () => {
    for (const [key, entry] of Object.entries(FACTOR_GUIDE)) {
      expect(entry.weight, key).toBeGreaterThan(0);
      for (const text of [entry.measures, entry.better, entry.why, entry.caveat]) {
        expect(text.trim().length, key).toBeGreaterThan(10);
      }
    }
    expect(MAX_FACTOR_WEIGHT).toBe(14);
  });

  it("matches the default weights in the scoring framework", () => {
    const weights = Object.fromEntries(
      Object.entries(FACTOR_GUIDE).map(([key, entry]) => [key, entry.weight]),
    );
    expect(weights).toEqual({
      grocery: 14,
      transit: 14,
      emergencyCorridor: 12,
      restaurant: 10,
      school: 10,
      gym: 9,
      cafe: 8,
      gasConvenience: 6,
      bar: 5,
      airport: 5,
      recreation: 5,
      shopping: 4,
      traffic: 4,
    });  });

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
