import { describe, expect, it } from "vitest";

import { FACTOR_KEYS } from "@/lib/score/factors";

import { ALL_FACTORS, createSelection } from "./selection";
import { DEFAULT_MAP_STATE, parseMapParams, serializeMapParams } from "./url";
import { mapHref } from "./viewport";

const parse = (query: string) => parseMapParams(new URLSearchParams(query));

describe("parseMapParams", () => {
  it("defaults to the whole metro, all factors, metro scope", () => {
    expect(parse("")).toEqual(DEFAULT_MAP_STATE);
  });

  it("reads the view and clamps the zoom", () => {
    expect(parse("lat=40.7&lon=-74&z=11.5").view).toEqual({
      lat: 40.7,
      lon: -74,
      zoom: 11.5,
    });
    expect(parse("lat=40.7&lon=-74&z=99").view?.zoom).toBe(19);
    expect(parse("lat=40.7&lon=-74").view?.zoom).toBe(12);
  });

  it("ignores an incomplete or out-of-range view", () => {
    expect(parse("lat=40.7").view).toBeNull();
    expect(parse("lat=95&lon=-74").view).toBeNull();
    expect(parse("lat=abc&lon=-74").view).toBeNull();
  });

  it("reads factors, dropping unknown keys", () => {
    expect(parse("factors=grocery,bogus,transit").selection.factors).toEqual([
      "grocery",
      "transit",
    ]);
  });

  it("falls back to all factors when none are recognised", () => {
    expect(parse("factors=bogus").selection).toEqual(ALL_FACTORS);
  });

  it("reads an explicit empty selection", () => {
    expect(parse("factors=none").selection.factors).toEqual([]);
  });

  it("reads importance only for known levels and selected factors", () => {
    const { selection } = parse(
      "factors=grocery,transit&importance=transit:high,grocery:low,cafe:high,gym:max",
    );
    expect(selection.importance).toEqual({ transit: "high", grocery: "low" });
  });

  it("applies importance to the all-factors default too", () => {
    expect(parse("importance=transit:high").selection.importance).toEqual({
      transit: "high",
    });
  });

  it("reads the scope", () => {
    expect(parse("scope=view").scope).toBe("view");
    expect(parse("scope=nonsense").scope).toBe("metro");
  });
});

describe("serializeMapParams", () => {
  it("omits defaults so the common URL stays short", () => {
    expect(serializeMapParams(DEFAULT_MAP_STATE)).toBe("");
  });

  it("round-trips a full state", () => {
    const state = {
      view: { lat: 40.7484, lon: -73.9857, zoom: 12.34 },
      selection: createSelection(["transit", "grocery"], { transit: "high" }),
      scope: "view" as const,
    };
    const query = serializeMapParams(state);
    expect(query).toBe(
      "lat=40.7484&lon=-73.9857&z=12.34&factors=grocery%2Ctransit&importance=transit%3Ahigh&scope=view",
    );
    expect(parse(query)).toEqual(state);
  });

  it("encodes an empty selection as none", () => {
    const query = serializeMapParams({
      ...DEFAULT_MAP_STATE,
      selection: createSelection([]),
    });
    expect(query).toBe("factors=none");
    expect(parse(query).selection.factors).toEqual([]);
  });

  it("does not write factors when every factor is selected", () => {
    expect(
      serializeMapParams({
        ...DEFAULT_MAP_STATE,
        selection: createSelection(FACTOR_KEYS),
      }),
    ).toBe("");
  });
});

describe("mapHref", () => {
  it("centres on a location", () => {
    expect(mapHref({ lat: 40.7492, lon: -73.985, zoom: 13 })).toBe(
      "/map?lat=40.7492&lon=-73.9850&z=13",
    );
  });
});
