import { describe, expect, it } from "vitest";

import { FACTOR_KEYS } from "@/lib/score/factors";

import { createSelection } from "./selection";
import { parseExplorerParams, serializeExplorerParams } from "./url";

describe("triangulation points in the URL", () => {
  const selection = createSelection(FACTOR_KEYS, {});

  it("defaults to no points and ignores malformed ones", () => {
    expect(parseExplorerParams(new URLSearchParams("")).points).toEqual([]);
    const bad = new URLSearchParams();
    for (const v of [
      "1,2",
      "x,y,walk,10",
      "40,-74,bike,10",
      "40,-74,walk,0",
      "40,-74,walk,10,9",
      "95,-74,drive,10",
      "40,-74,walk,1.5",
    ]) {
      bad.append("pt", v);
    }
    expect(parseExplorerParams(bad).points).toEqual([]);
  });

  it("round-trips repeated pt params", () => {
    const points = [
      { lat: 40.7484, lon: -73.9857, mode: "transit" as const, minutes: 20 },
      { lat: 40.668, lon: -73.985, mode: "drive" as const, minutes: 15 },
    ];
    const query = serializeExplorerParams({ target: null, view: null, selection, points });
    expect(new URLSearchParams(query).getAll("pt")).toHaveLength(2);
    expect(parseExplorerParams(new URLSearchParams(query)).points).toEqual(points);
  });

  it("omits pt without points and keeps at most three", () => {
    expect(serializeExplorerParams({ target: null, view: null, selection })).toBe("");
    const many = Array.from({ length: 5 }, (_, i) => ({
      lat: 40 + i / 10,
      lon: -74,
      mode: "walk" as const,
      minutes: 10,
    }));
    const query = serializeExplorerParams({ target: null, view: null, selection, points: many });
    expect(new URLSearchParams(query).getAll("pt")).toHaveLength(3);
  });
});
