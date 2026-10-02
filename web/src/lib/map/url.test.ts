import { describe, expect, it } from "vitest";

import { FACTOR_KEYS } from "@/lib/score/factors";

import { ALL_FACTORS, createSelection } from "./selection";
import {
  explorerHref,
  initialView,
  legacyMapQuery,
  parseExplorerParams,
  serializeExplorerParams,
  type ExplorerUrlInput,
} from "./url";

const parse = (query: string) => parseExplorerParams(new URLSearchParams(query));

const EMPTY: ExplorerUrlInput = {
  target: null,
  view: null,
  selection: ALL_FACTORS,
};

describe("parseExplorerParams", () => {
  it("defaults to no place, no view, all factors", () => {
    expect(parse("")).toEqual({
      target: null,
      targetError: null,
      center: null,
      zoom: null,
      selection: ALL_FACTORS,
    });
  });

  it("ignores a retired paths=1 param and never re-serialises it", () => {
    const state = parse("paths=1");
    expect(state).not.toHaveProperty("showPaths");
    expect(serializeExplorerParams({ ...EMPTY, ...state })).toBe("");
  });

  it("reads an address, with or without coordinates", () => {
    expect(parse("address=Grand+Central+Terminal").target).toEqual({
      kind: "address",
      address: "Grand Central Terminal",
    });
    expect(parse("address=x&lat=40.7527&lon=-73.9772").target).toEqual({
      kind: "coordinates",
      lat: 40.7527,
      lon: -73.9772,
      label: "40.7527, -73.9772",
    });
    expect(parse("address=Home+base&lat=40.7&lon=-74").target).toMatchObject({
      kind: "coordinates",
      label: "Home base",
    });
  });

  it("reports an unusable address", () => {
    const state = parse("address=a");
    expect(state.target).toBeNull();
    expect(state.targetError).toMatch(/at least 3 characters/);
  });

  it("reads the view and clamps the zoom", () => {
    expect(parse("center=40.7,-74&z=11.5")).toMatchObject({
      center: { lat: 40.7, lon: -74 },
      zoom: 11.5,
    });
    expect(parse("z=99").zoom).toBe(19);
    expect(parse("z=1").zoom).toBe(3);
  });

  it("ignores an incomplete or out-of-range centre", () => {
    expect(parse("center=40.7").center).toBeNull();
    expect(parse("center=95,-74").center).toBeNull();
    expect(parse("center=abc,-74").center).toBeNull();
    expect(parse("center=1,2,3").center).toBeNull();
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

  it("falls back to a scored place, close up", () => {
    expect(initialView(parse("lat=40.7&lon=-74"))).toEqual({
      lat: 40.7,
      lon: -74,
      zoom: 14,
    });
    expect(initialView(parse("lat=40.7&lon=-74&z=11"))?.zoom).toBe(11);
  });

  it("leaves the metro overview for an address that is not geocoded yet", () => {
    expect(initialView(parse("address=Grand+Central"))).toBeNull();
    expect(initialView(parse("z=11"))).toBeNull();
    expect(initialView(parse(""))).toBeNull();
  });
});

describe("serializeExplorerParams", () => {
  it("omits defaults so the common URL stays short", () => {
    expect(serializeExplorerParams(EMPTY)).toBe("");
    expect(explorerHref(EMPTY)).toBe("/app");
  });

  it("writes an address, and coordinates with their label", () => {
    expect(
      serializeExplorerParams({
        ...EMPTY,
        target: { kind: "address", address: "350 5th Ave, New York" },
      }),
    ).toBe("address=350+5th+Ave%2C+New+York");
    expect(
      serializeExplorerParams({
        ...EMPTY,
        target: { kind: "coordinates", lat: 40.7, lon: -74, label: "Home" },
      }),
    ).toBe("address=Home&lat=40.7&lon=-74");
  });

  it("does not repeat coordinates as their own label", () => {
    expect(
      explorerHref({
        ...EMPTY,
        target: {
          kind: "coordinates",
          lat: 40.7527,
          lon: -73.9772,
          label: "40.7527, -73.9772",
        },
      }),
    ).toBe("/app?lat=40.7527&lon=-73.9772");
  });

  it("leaves the centre out while the map is on the scored place", () => {
    const target = {
      kind: "coordinates" as const,
      lat: 40.7484,
      lon: -73.9857,
      label: "x y",
    };
    expect(
      serializeExplorerParams({
        ...EMPTY,
        target,
        view: { lat: 40.74841, lon: -73.98572, zoom: 14 },
      }),
    ).toBe("address=x+y&lat=40.7484&lon=-73.9857&z=14");
    expect(
      serializeExplorerParams({
        ...EMPTY,
        target,
        view: { lat: 40.8, lon: -73.9, zoom: 14 },
      }),
    ).toContain("center=40.8000%2C-73.9000");
  });

  it("round-trips a full state", () => {
    const input: ExplorerUrlInput = {
      target: { kind: "coordinates", lat: 40.7, lon: -74, label: "Home" },
      view: { lat: 40.7484, lon: -73.9857, zoom: 12.34 },
      selection: createSelection(["transit", "grocery"], { transit: "high" }),
    };
    const query = serializeExplorerParams(input);
    expect(query).toBe(
      "address=Home&lat=40.7&lon=-74&center=40.7484%2C-73.9857&z=12.34&factors=grocery%2Ctransit&importance=transit%3Ahigh",
    );
    const state = parse(query);
    expect(state.target).toEqual(input.target);
    expect(state.center).toEqual({ lat: 40.7484, lon: -73.9857 });
    expect(state.zoom).toBe(12.34);
    expect(state.selection).toEqual(input.selection);
  });

  it("encodes an empty selection as none", () => {
    const query = serializeExplorerParams({
      ...EMPTY,
      selection: createSelection([]),
    });
    expect(query).toBe("factors=none");
    expect(parse(query).selection.factors).toEqual([]);
  });

  it("does not write factors when every factor is selected", () => {
    expect(
      serializeExplorerParams({
        ...EMPTY,
        selection: createSelection(FACTOR_KEYS),
      }),
    ).toBe("");
  });
});

describe("legacyMapQuery", () => {
  it("turns the old view centre into a centre and keeps the rest", () => {
    const query = legacyMapQuery({
      lat: "40.75",
      lon: "-73.99",
      z: "13",
      factors: "transit",
      importance: "transit:high",
    });
    const state = parse(query);
    expect(state.target).toBeNull();
    expect(state.center).toEqual({ lat: 40.75, lon: -73.99 });
    expect(state.zoom).toBe(13);
    expect(state.selection.factors).toEqual(["transit"]);
    expect(state.selection.importance).toEqual({ transit: "high" });
  });

  it("never turns a map link into a scored place", () => {
    expect(new URLSearchParams(legacyMapQuery({ lat: "40.75", lon: "-73.99" })).has("lat")).toBe(false);
  });

  it("drops an unusable centre", () => {
    expect(legacyMapQuery({ lat: "abc", lon: "-73.99", z: "13" })).toBe("z=13");
    expect(legacyMapQuery({ lat: "40.75" })).toBe("");
  });

  it("is empty for a bare /map", () => {
    expect(legacyMapQuery({})).toBe("");
  });

  it("takes the first of a repeated parameter", () => {
    expect(legacyMapQuery({ z: ["12", "14"] })).toBe("z=12");
  });
});
