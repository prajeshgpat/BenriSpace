import { describe, expect, it } from "vitest";

import { DEFAULT_SELECTION } from "./selection";
import { parseExplorerParams, serializeExplorerParams } from "./url";

describe("points of interest in the URL", () => {
  const selection = DEFAULT_SELECTION;

  it("defaults to no points and ignores malformed ones", () => {
    expect(parseExplorerParams(new URLSearchParams("")).points).toEqual([]);
    const bad = new URLSearchParams();
    for (const v of ["1", "x,y", "95,-74", "40,-74,walk", "40,-74,walk,10,9"]) {
      bad.append("pt", v);
    }
    expect(parseExplorerParams(bad).points).toEqual([]);
  });

  it("round-trips repeated pt=lat,lon params", () => {
    const points = [
      { lat: 40.7484, lon: -73.9857 },
      { lat: 40.668, lon: -73.985 },
    ];
    const query = serializeExplorerParams({ target: null, view: null, selection, points });
    expect(new URLSearchParams(query).getAll("pt")).toEqual(["40.74840,-73.98570", "40.66800,-73.98500"]);
    expect(parseExplorerParams(new URLSearchParams(query)).points).toEqual(points);
  });

  it("still reads the older lat,lon,mode,minutes form and ignores mode and minutes", () => {
    const legacy = new URLSearchParams();
    legacy.append("pt", "40.7484,-73.9857,transit,20");
    legacy.append("pt", "40.668,-73.985,drive,15");
    expect(parseExplorerParams(legacy).points).toEqual([
      { lat: 40.7484, lon: -73.9857 },
      { lat: 40.668, lon: -73.985 },
    ]);
  });

  it("omits pt without points and keeps at most two", () => {
    expect(serializeExplorerParams({ target: null, view: null, selection })).toBe("");
    const many = Array.from({ length: 5 }, (_, i) => ({ lat: 40 + i / 10, lon: -74 }));
    const query = serializeExplorerParams({ target: null, view: null, selection, points: many });
    expect(new URLSearchParams(query).getAll("pt")).toHaveLength(2);
    expect(parseExplorerParams(new URLSearchParams(query)).points).toHaveLength(2);
  });
});
