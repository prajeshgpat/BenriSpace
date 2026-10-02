import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api/errors";
import { emptySubScores, fullSubScores } from "@/test/fixtures";

import {
  areaTitle,
  describeMapStatus,
  metroLabel,
  strongestFactors,
} from "./presentation";

describe("strongestFactors", () => {
  it("picks the best two of the selected factors only", () => {
    const result = strongestFactors(fullSubScores, [
      "gasStation",
      "grocery",
      "cafe",
      "road",
    ]);
    expect(result.map((f) => f.key)).toEqual(["grocery", "cafe"]);
    expect(result[0]).toEqual({
      key: "grocery",
      label: "Grocery stores",
      value: 91,
    });
  });

  it("ignores a stronger factor that is not selected", () => {
    const result = strongestFactors(fullSubScores, ["road"]);
    expect(result.map((f) => f.key)).toEqual(["road"]);
  });

  it("skips factors with no data", () => {
    expect(
      strongestFactors({ ...emptySubScores, cafe: 50 }, ["grocery", "cafe"]),
    ).toHaveLength(1);
    expect(strongestFactors(emptySubScores, ["grocery"])).toEqual([]);
  });

  it("keeps selection order on ties", () => {
    const tied = { ...emptySubScores, gym: 80, cafe: 80, grocery: 80 };
    expect(
      strongestFactors(tied, ["cafe", "grocery", "gym"]).map((f) => f.key),
    ).toEqual(["cafe", "grocery"]);
  });
});

describe("labels", () => {
  it("names known metros and shouts unknown ones", () => {
    expect(metroLabel("nyc")).toBe("New York");
    expect(metroLabel("bos")).toBe("BOS");
    expect(metroLabel("")).toBe("Metro area");
  });

  it("titles an area by its coordinates", () => {
    expect(
      areaTitle({ latitude: 40.7546, longitude: -73.985, metroArea: "nyc" }),
    ).toBe("Area near 40.755, -73.985");
  });
});

describe("describeMapStatus", () => {
  const ok = { status: "ready", count: 0, error: null } as const;

  it("asks for a factor when none is selected", () => {
    expect(describeMapStatus({ noFactors: true, cells: ok, top: ok })).toMatch(
      /Select at least one/,
    );
  });

  it("announces loading and result counts", () => {
    expect(
      describeMapStatus({
        noFactors: false,
        cells: ok,
        top: { status: "loading", count: 0, error: null },
      }),
    ).toContain("Finding the best areas");
    expect(
      describeMapStatus({
        noFactors: false,
        cells: { ...ok, count: 5 },
        top: { ...ok, count: 10 },
      }),
    ).toBe("10 best areas found.");
    expect(
      describeMapStatus({
        noFactors: false,
        cells: { ...ok, count: 5 },
        top: { ...ok, count: 1 },
      }),
    ).toBe("1 best area found.");
  });

  it("announces an empty viewport", () => {
    expect(
      describeMapStatus({
        noFactors: false,
        cells: ok,
        top: { ...ok, count: 3 },
      }),
    ).toBe("3 best areas found. No scored cells in view.");
  });

  it("describes a rate limit in plain words", () => {
    const error = new ApiError("rate-limited", "x", { status: 429 });
    const message = describeMapStatus({
      noFactors: false,
      cells: { status: "error", count: 0, error },
      top: { status: "idle", count: 0, error: null },
    });
    expect(message).toContain("Too many requests");
  });
});
