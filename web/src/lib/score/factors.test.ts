import { describe, expect, it } from "vitest";

import {
  FACTOR_GROUPS,
  FACTOR_KEYS,
  FACTORS,
  canonicalFactorKey,
} from "./factors";

describe("factors", () => {
  it("has the thirteen v1.4 pills with their labels", () => {
    expect(Object.fromEntries(FACTOR_KEYS.map((k) => [k, FACTORS[k].label]))).toEqual({
      grocery: "Groceries",
      restaurant: "Restaurants",
      cafe: "Cafes",
      bar: "Bars",
      gym: "Gym",
      shopping: "Shopping",
      transit: "Public transit",
      airport: "Airport",
      gasConvenience: "Gas & Convenience",
      traffic: "Traffic",
      school: "Schools",
      emergencyCorridor: "Noise corridor",
      recreation: "Recreation",
    });
  });

  it("groups them as the framework specifies", () => {
    const groupOf = (group: string) =>
      FACTOR_KEYS.filter((k) => FACTORS[k].group === group).sort();
    expect(FACTOR_GROUPS).toEqual({
      amenities: "Daily amenities",
      mobility: "Getting around",
      neighborhood: "Neighborhood",
    });
    expect(groupOf("amenities")).toEqual(
      ["bar", "cafe", "grocery", "gym", "restaurant", "shopping"].sort(),
    );
    expect(groupOf("mobility")).toEqual(
      ["airport", "gasConvenience", "traffic", "transit"].sort(),
    );
    expect(groupOf("neighborhood")).toEqual(
      ["emergencyCorridor", "recreation", "school"].sort(),
    );
  });

  it("resolves legacy aliases and rejects unknown keys", () => {
    expect(canonicalFactorKey("premiumRetail")).toBe("shopping");
    expect(canonicalFactorKey("trailPopularity")).toBe("recreation");
    expect(canonicalFactorKey("road")).toBe("traffic");
    expect(canonicalFactorKey("gasStation")).toBe("gasConvenience");
    expect(canonicalFactorKey("convenienceStore")).toBe("gasConvenience");
    expect(canonicalFactorKey("grocery")).toBe("grocery");
    expect(canonicalFactorKey("toString")).toBeNull();
    expect(canonicalFactorKey(3)).toBeNull();
  });
});
