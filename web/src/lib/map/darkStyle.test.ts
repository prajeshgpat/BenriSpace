import { describe, expect, it } from "vitest";

import { DARK_PALETTE, tuneDarkStyle } from "./darkStyle";

function fixture() {
  return {
    version: 8,
    sources: { openmaptiles: { type: "vector", url: "x" } },
    layers: [
      {
        id: "background",
        type: "background",
        paint: { "background-color": "#000" },
      },
      {
        id: "water",
        type: "fill",
        "source-layer": "water",
        paint: { "fill-color": "#111" },
      },
      {
        id: "landcover_wood",
        type: "fill",
        "source-layer": "landcover",
        paint: {
          "fill-color": "#222",
          "fill-pattern": "wood-pattern",
          "fill-opacity": 0.4,
        },
      },
      {
        id: "building",
        type: "fill",
        "source-layer": "building",
        paint: { "fill-color": "#0a0a0a" },
      },
      {
        id: "highway_motorway_inner",
        type: "line",
        "source-layer": "transportation",
        paint: {
          "line-color": [
            "interpolate",
            ["linear"],
            ["zoom"],
            5,
            "#fff",
            6,
            "#000",
          ],
          "line-width": 2,
        },
      },
      {
        id: "railway_dashline",
        type: "line",
        "source-layer": "transportation",
        paint: { "line-color": "#000" },
      },
      {
        id: "water_name",
        type: "symbol",
        "source-layer": "water_name",
        paint: { "text-color": "#000" },
      },
      {
        id: "place_city",
        type: "symbol",
        "source-layer": "place",
        paint: { "text-color": "#666" },
      },
      { id: "mystery", type: "circle", paint: { "circle-color": "#123" } },
    ],
  };
}

function byId(style: ReturnType<typeof fixture>, id: string) {
  const layer = style.layers.find((l) => l.id === id);
  if (!layer) throw new Error(id);
  return layer as { paint: Record<string, unknown> };
}

describe("tuneDarkStyle", () => {
  it("makes water a distinct blue and land a neutral dark grey", () => {
    const out = tuneDarkStyle(fixture());
    expect(byId(out, "water").paint["fill-color"]).toBe(DARK_PALETTE.water);
    expect(byId(out, "background").paint["background-color"]).toBe(
      DARK_PALETTE.land,
    );
    expect(DARK_PALETTE.water).not.toBe(DARK_PALETTE.land);
  });

  it("recolours woods green and drops their texture", () => {
    const wood = byId(tuneDarkStyle(fixture()), "landcover_wood");
    expect(wood.paint["fill-color"]).toBe(DARK_PALETTE.park);
    expect("fill-pattern" in wood.paint).toBe(false);
  });

  it("replaces expression colours and keeps other paint properties", () => {
    const road = byId(tuneDarkStyle(fixture()), "highway_motorway_inner");
    expect(road.paint["line-color"]).toBe(DARK_PALETTE.motorway);
    expect(road.paint["line-width"]).toBe(2);
  });

  it("styles buildings, rail dashes and labels", () => {
    const out = tuneDarkStyle(fixture());
    expect(byId(out, "building").paint["fill-color"]).toBe(
      DARK_PALETTE.building,
    );
    expect(byId(out, "railway_dashline").paint["line-color"]).toBe(
      DARK_PALETTE.land,
    );
    expect(byId(out, "water_name").paint["text-color"]).toBe(
      DARK_PALETTE.waterLabel,
    );
    expect(byId(out, "place_city").paint["text-halo-color"]).toBe(
      DARK_PALETTE.labelHalo,
    );
  });

  it("leaves unknown layers alone and does not mutate the input", () => {
    const input = fixture();
    const out = tuneDarkStyle(input);
    expect(byId(out, "mystery").paint).toEqual({ "circle-color": "#123" });
    expect(input).toEqual(fixture());
  });

  it("tolerates missing layers and malformed input", () => {
    expect(tuneDarkStyle({ version: 8, layers: [] })).toEqual({
      version: 8,
      layers: [],
    });
    const noLayers = { version: 8 };
    expect(tuneDarkStyle(noLayers)).toBe(noLayers);
    expect(tuneDarkStyle(null)).toBeNull();
    const odd = {
      layers: [null, 3, { type: "fill" }, { id: "water", type: "fill" }],
    };
    expect(() => tuneDarkStyle(odd)).not.toThrow();
  });

  it("returns the original style if tuning throws", () => {
    const hostile = {
      get layers(): unknown {
        throw new Error("boom");
      },
    };
    expect(tuneDarkStyle(hostile)).toBe(hostile);
  });
});
