import type { LayerSpecification, Map as MaplibreMap } from "maplibre-gl";
import { describe, expect, it } from "vitest";

import { addWaterMask, firstWaterMaskId, isOverWater, waterMaskLayers } from "./waterMask";

const L = (o: Record<string, unknown>) => o as unknown as LayerSpecification;
const layers = [
  L({ id: "bg", type: "background" }),
  L({ id: "water", type: "fill", source: "o", "source-layer": "water", filter: ["==", "a", 1], paint: { "fill-color": "#00f" }, minzoom: 2 }),
  L({ id: "park", type: "fill", source: "o", "source-layer": "park" }),
  L({ id: "river", type: "line", source: "o", "source-layer": "waterway", paint: { "line-color": "#00f" } }),
  L({ id: "water-line", type: "line", source: "o", "source-layer": "water" }),
  L({ id: "label", type: "symbol", source: "o", "source-layer": "water_name" }),
];

function fakeMap(initial: LayerSpecification[]) {
  const list = [...initial];
  const map = {
    getStyle: () => ({ layers: list }),
    removeLayer: (id: string) => void list.splice(list.findIndex((l) => l.id === id), 1),
    addLayer: (layer: LayerSpecification, before?: string) => {
      const i = before ? list.findIndex((l) => l.id === before) : -1;
      list.splice(i < 0 ? list.length : i, 0, layer);
    },
    queryRenderedFeatures: () => [{}],
  };
  return { map: map as unknown as MaplibreMap, list };
}

describe("waterMaskLayers", () => {
  it("clones only water fills and waterway lines with stable ids", () => {
    const out = waterMaskLayers(layers);
    expect(out.map((l) => l.id)).toEqual(["benri-water:water", "benri-water:river"]);
    expect(out[0]).toMatchObject({ source: "o", "source-layer": "water", minzoom: 2, filter: ["==", "a", 1], paint: { "fill-color": "#00f" } });
    expect(waterMaskLayers(layers).map((l) => l.id)).toEqual(out.map((l) => l.id));
  });
  it("does not re-clone masks", () => {
    expect(waterMaskLayers(waterMaskLayers(layers))).toEqual([]);
  });
});

describe("addWaterMask", () => {
  it("inserts before the anchor and is idempotent", () => {
    const { map, list } = fakeMap(layers);
    addWaterMask(map, "label");
    addWaterMask(map, "label");
    const ids = list.map((l) => l.id);
    expect(ids.filter((id) => id.startsWith("benri-water:"))).toHaveLength(2);
    expect(ids.indexOf("benri-water:river")).toBe(ids.indexOf("label") - 1);
    expect(firstWaterMaskId(map)).toBe("benri-water:water");
  });
  it("never throws", () => {
    const broken = { getStyle: () => { throw new Error("x"); } } as unknown as MaplibreMap;
    expect(() => addWaterMask(broken, undefined)).not.toThrow();
    expect(firstWaterMaskId(broken)).toBeUndefined();
    expect(isOverWater(broken, { x: 0, y: 0 })).toBe(false);
  });
  it("reports water under a point only when a mask exists", () => {
    const { map } = fakeMap(layers);
    expect(isOverWater(map, { x: 1, y: 1 })).toBe(false);
    addWaterMask(map, undefined);
    expect(isOverWater(map, { x: 1, y: 1 })).toBe(true);
  });
});
