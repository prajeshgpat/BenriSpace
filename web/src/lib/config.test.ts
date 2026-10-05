import { describe, expect, it } from "vitest";

import { resolveScorePrecision } from "./config";

describe("resolveScorePrecision", () => {
  it("defaults to grid", () => {
    expect(resolveScorePrecision(undefined)).toBe("grid");
    expect(resolveScorePrecision("")).toBe("grid");
    expect(resolveScorePrecision("exact")).toBe("grid");
  });

  it("accepts point in any case", () => {
    expect(resolveScorePrecision("point")).toBe("point");
    expect(resolveScorePrecision(" Point ")).toBe("point");
  });
});
