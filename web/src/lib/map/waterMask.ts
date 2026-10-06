import type { LayerSpecification, Map as MaplibreMap } from "maplibre-gl";

/** Prefix of the cloned basemap water layers drawn above the score cells. */
export const WATER_MASK_PREFIX = "benri-water:";

type AnyLayer = LayerSpecification & { "source-layer"?: string };

/**
 * Copies of the basemap's water fills and waterway lines, so they can be
 * drawn again above the score cells and water shows as plain basemap blue.
 */
export function waterMaskLayers(styleLayers: readonly LayerSpecification[]): LayerSpecification[] {
  const out: LayerSpecification[] = [];
  for (const layer of styleLayers) {
    const sourceLayer = (layer as AnyLayer)["source-layer"];
    const isWater =
      (layer.type === "fill" && sourceLayer === "water") ||
      (layer.type === "line" && sourceLayer === "waterway");
    if (!isWater || layer.id.startsWith(WATER_MASK_PREFIX)) continue;
    out.push({ ...structuredClone(layer), id: WATER_MASK_PREFIX + layer.id } as LayerSpecification);
  }
  return out;
}

function maskIds(map: MaplibreMap): string[] {
  try {
    return map
      .getStyle()
      .layers.map((layer) => layer.id)
      .filter((id) => id.startsWith(WATER_MASK_PREFIX));
  } catch {
    return [];
  }
}

/** Replaces any earlier mask with fresh clones, inserted before `beforeId`. Never throws. */
export function addWaterMask(map: MaplibreMap, beforeId: string | undefined): void {
  try {
    for (const id of maskIds(map)) {
      try {
        map.removeLayer(id);
      } catch {
        // Already gone.
      }
    }
    for (const layer of waterMaskLayers(map.getStyle().layers)) {
      try {
        map.addLayer(layer, beforeId);
      } catch {
        // A layer whose source is missing is skipped; the rest still apply.
      }
    }
  } catch {
    // The map is mid-teardown.
  }
}

export function firstWaterMaskId(map: MaplibreMap): string | undefined {
  return maskIds(map)[0];
}

/** True when a screen point lies on basemap water (so not on a score cell). */
export function isOverWater(map: MaplibreMap, point: { x: number; y: number }): boolean {
  try {
    const layers = maskIds(map);
    if (layers.length === 0) return false;
    return map.queryRenderedFeatures(point as never, { layers }).length > 0;
  } catch {
    return false;
  }
}
