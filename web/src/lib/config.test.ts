import { describe, expect, it } from "vitest";

import { resolveScorePrecision, resolveStaticUrl } from "./config";

describe("resolveStaticUrl", () => {
  it("is off unless set to an https (or localhost) URL, without a trailing slash", () => {
    expect(resolveStaticUrl(undefined)).toBeUndefined();
    expect(resolveStaticUrl("  ")).toBeUndefined();
    expect(resolveStaticUrl("http://tiles.example.com")).toBeUndefined();
    expect(resolveStaticUrl("nonsense")).toBeUndefined();
    expect(resolveStaticUrl("https://tiles.benrispace.com")).toBe("https://tiles.benrispace.com");
    expect(resolveStaticUrl("https://tiles.benrispace.com/")).toBe("https://tiles.benrispace.com");
    expect(resolveStaticUrl("http://localhost:9000/")).toBe("http://localhost:9000");
  });
});

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
