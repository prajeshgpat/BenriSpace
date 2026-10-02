import type { LayerSpecification } from "maplibre-gl";
import { describe, expect, it } from "vitest";

import { overlayAnchorId } from "./overlayAnchor";

const layer = (id: string, type: string, sourceLayer?: string) =>
  ({ id, type, "source-layer": sourceLayer }) as unknown as LayerSpecification;

// The order of OpenFreeMap's dark style, trimmed.
const DARK = [
  layer("background", "background"),
  layer("water", "fill", "water"),
  layer("water_name", "symbol", "water_name"),
  layer("building", "fill", "building"),
  layer("highway_minor", "line", "transportation"),
  layer("highway_motorway_inner", "line", "transportation"),
  layer("road_oneway", "symbol", "transportation"),
  layer("railway", "line", "transportation"),
  layer("highway_name_other", "symbol", "transportation_name"),
  layer("boundary_state", "line", "boundary"),
  layer("place_city", "symbol", "place"),
];

describe("overlayAnchorId", () => {
  it("light mode keeps the first symbol layer", () => {
    expect(overlayAnchorId(DARK, "light")).toBe("water_name");
  });

  it("dark mode goes above the buildings and roads, under the road labels", () => {
    expect(overlayAnchorId(DARK, "dark")).toBe("highway_name_other");
  });

  it("falls back to the first symbol when nothing is road or building", () => {
    const layers = [layer("water", "fill", "water"), layer("label", "symbol", "x")];
    expect(overlayAnchorId(layers, "dark")).toBe("label");
  });

  it("returns undefined (add on top) when there are no symbol layers", () => {
    expect(overlayAnchorId([layer("water", "fill", "water")], "dark")).toBeUndefined();
  });
});
