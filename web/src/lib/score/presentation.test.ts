import { describe, expect, it } from "vitest";

import { emptySubScores, fullSubScores } from "@/test/fixtures";

import { FACTOR_KEYS, FACTORS } from "./factors";
import {
  NO_DATA_LABEL,
  bandLabel,
  buildFactorSections,
  describeScoredLocation,
  formatComputedAt,
  formatCoordinates,
  isCoordinateAddress,
  roundScore,
  scoreBand,
  summarizeCoverage,
} from "./presentation";

describe("roundScore", () => {
  it.each([
    [62.7906976744186, 63],
    [62.4, 62],
    [0, 0],
    [100, 100],
    [-4, 0],
    [131.2, 100],
  ])("rounds %d to %d within 0-100", (input, expected) => {
    expect(roundScore(input)).toBe(expected);
  });
});

describe("scoreBand", () => {
  it.each([
    [100, "excellent"],
    [80, "excellent"],
    [79.5, "excellent"],
    [79.4, "good"],
    [60, "good"],
    [59.4, "fair"],
    [40, "fair"],
    [39.4, "limited"],
    [0, "limited"],
  ] as const)("places %d in the %s band", (value, band) => {
    expect(scoreBand(value)).toBe(band);
  });

  it("bands on the rounded value so the label never contradicts the number shown", () => {
    expect(roundScore(79.5)).toBe(80);
    expect(bandLabel(79.5)).toBe("Excellent");
  });
});

describe("buildFactorSections", () => {
  const rowsOf = (subScores: typeof fullSubScores) =>
    buildFactorSections(subScores).flatMap((section) => section.rows);

  it("covers every contract factor exactly once, grouped under a titled section", () => {
    const sections = buildFactorSections(fullSubScores);
    const keys = sections.flatMap((section) => section.rows.map((row) => row.key));

    expect([...keys].sort()).toEqual([...FACTOR_KEYS].sort());
    expect(sections.map((section) => section.title)).toEqual([
      "Daily amenities",
      "Getting around",
      "Neighborhood",
    ]);
    expect(sections.every((section) => section.rows.length > 0)).toBe(true);
  });

  it("labels each factor in human terms", () => {
    const labels = Object.fromEntries(
      rowsOf(fullSubScores).map((row) => [row.key, row.label]),
    );

    expect(labels).toMatchObject({
      grocery: "Grocery stores",
      gasStation: "Gas stations",
      convenienceStore: "Convenience stores",
      emergencyCorridor: "Noise corridor",
      restaurant: "Restaurants",
      bar: "Bars & pubs",
    });
  });

  it("renders a missing sub-score as no data, never as zero", () => {
    const rows = rowsOf({ ...emptySubScores, airport: 62.79 });
    const grocery = rows.find((row) => row.key === "grocery");

    expect(grocery).toMatchObject({
      value: null,
      display: NO_DATA_LABEL,
      band: null,
    });
    expect(rows.filter((row) => row.value === null)).toHaveLength(
      FACTOR_KEYS.length - 1,
    );
  });

  it("keeps a real zero as a scored value", () => {
    const zero = rowsOf(fullSubScores).find(
      (row) => row.key === "emergencyCorridor",
    );

    expect(zero).toMatchObject({ value: 0, display: "0", band: "Limited" });
  });

  it("rounds values for display and attaches a band", () => {
    const airport = rowsOf(fullSubScores).find((row) => row.key === "airport");

    expect(airport).toMatchObject({ value: 63, display: "63", band: "Good" });
  });

  it("explains the direction of every inverted factor", () => {
    for (const key of ["gasStation", "convenienceStore", "road"] as const) {
      expect(FACTORS[key].description).toMatch(/^Higher means/);
    }
  });
});

describe("summarizeCoverage", () => {
  it("reports full coverage", () => {
    expect(summarizeCoverage(fullSubScores)).toMatchObject({
      available: 12,
      total: 12,
      isComplete: true,
      summary: "Based on all 12 factors.",
    });
  });

  it("flags a composite built from partial data", () => {
    const coverage = summarizeCoverage({ ...emptySubScores, airport: 62.79 });

    expect(coverage).toMatchObject({ available: 1, total: 12, isComplete: false });
    expect(coverage.summary).toMatch(/^Based on 1 of 12 factors\./);
  });

  it("counts a zero score as available data", () => {
    expect(summarizeCoverage({ ...emptySubScores, road: 0 }).available).toBe(1);
  });

  it("handles a score with no breakdown at all", () => {
    expect(summarizeCoverage(emptySubScores)).toMatchObject({
      available: 0,
      isComplete: false,
      summary: "No factor breakdown is available for this area yet.",
    });
  });
});

describe("location description", () => {
  it.each([
    ["40.74920,-73.98500", true],
    [" 40.7 , -73.9 ", true],
    ["350 5th Ave, New York, NY", false],
    ["10001", false],
    ["", false],
  ])("isCoordinateAddress(%j) is %s", (address, expected) => {
    expect(isCoordinateAddress(address)).toBe(expected);
  });

  it("formats coordinates with hemispheres", () => {
    expect(formatCoordinates(40.7492000000001, -73.9850000000001)).toBe(
      "40.7492° N, 73.9850° W",
    );
    expect(formatCoordinates(-33.86, 151.21)).toBe("33.8600° S, 151.2100° E");
  });

  it("does not present a lat,lon pair as a street address", () => {
    expect(
      describeScoredLocation({
        address: "40.74920,-73.98500",
        latitude: 40.7492,
        longitude: -73.985,
      }),
    ).toBe("Scored for the area around 40.7492° N, 73.9850° W");
  });

  it("includes a real address when the API provides one", () => {
    expect(
      describeScoredLocation({
        address: "350 5th Ave, New York, NY 10118",
        latitude: 40.7492,
        longitude: -73.985,
      }),
    ).toBe("Scored for 350 5th Ave, New York, NY 10118 (40.7492° N, 73.9850° W)");
  });
});

describe("formatComputedAt", () => {
  it("formats an ISO timestamp as a readable date", () => {
    expect(
      formatComputedAt("2026-09-29T03:12:03.491922Z", { timeZone: "UTC" }),
    ).toBe("Sep 29, 2026");
  });

  it("returns null for an unparseable timestamp", () => {
    expect(formatComputedAt("not a date")).toBeNull();
  });
});
