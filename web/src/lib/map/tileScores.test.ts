import { describe, expect, it } from "vitest";

import { diffTileScores, tileScoresOf } from "./tileScores";
import { resolveTilesUrl } from "@/lib/config";

describe("tile score joins", () => {
  it("maps geohashes to scores", () => {
    const scores = tileScoresOf({ precision: 6, geohashes: ["a", "b"], scores: [10, 20] });
    expect([...scores]).toEqual([["a", 10], ["b", 20]]);
  });

  it("sets only changed cells and clears the ones that lost a score", () => {
    const previous = new Map([["a", 10], ["b", 20], ["c", 30]]);
    const next = new Map([["a", 10], ["b", 25], ["d", 40]]);
    expect(diffTileScores(previous, next)).toEqual({
      set: [["b", 25], ["d", 40]],
      remove: ["c"],
    });
    expect(diffTileScores(next, next)).toEqual({ set: [], remove: [] });
  });
});

describe("resolveTilesUrl", () => {
  it("is off by default and accepts only https or local http", () => {
    expect(resolveTilesUrl(undefined)).toBeUndefined();
    expect(resolveTilesUrl("  ")).toBeUndefined();
    expect(resolveTilesUrl("http://example.com/t.pmtiles")).toBeUndefined();
    expect(resolveTilesUrl("not a url")).toBeUndefined();
    expect(resolveTilesUrl("https://tiles.example.com/b.pmtiles")).toBe(
      "https://tiles.example.com/b.pmtiles",
    );
    expect(resolveTilesUrl("http://localhost:8080/b.pmtiles")).toBe(
      "http://localhost:8080/b.pmtiles",
    );
  });
});
