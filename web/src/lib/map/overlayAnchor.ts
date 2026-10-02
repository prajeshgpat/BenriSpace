import type { LayerSpecification } from "maplibre-gl";

import type { ResolvedTheme } from "@/lib/theme";

/** Basemap layers that must stay under our overlays, or the overlays disappear. */
const BASE_SOURCE_LAYERS = new Set(["transportation", "building", "aeroway"]);

function isBaseGeometry(layer: LayerSpecification): boolean {
  if (layer.type !== "fill" && layer.type !== "line" && layer.type !== "fill-extrusion") {
    return false;
  }
  const sourceLayer = (layer as { "source-layer"?: string })["source-layer"];
  return sourceLayer !== undefined && BASE_SOURCE_LAYERS.has(sourceLayer);
}

/**
 * The id of the basemap layer our overlays (score cells, the area outline) are
 * inserted before, so place names stay readable on top of them.
 *
 * Light: the first symbol layer, as the Liberty style orders it.
 * Dark: OpenFreeMap's dark style puts a water label *before* its buildings and
 * roads, so inserting under the first symbol would bury the overlays beneath
 * them once those layers appear at high zoom. Use the first symbol layer after
 * the last road/building layer instead.
 */
export function overlayAnchorId(
  layers: readonly LayerSpecification[],
  theme: ResolvedTheme,
): string | undefined {
  const firstSymbol = layers.find((layer) => layer.type === "symbol");
  if (theme === "light") return firstSymbol?.id;

  let lastBase = -1;
  layers.forEach((layer, index) => {
    if (isBaseGeometry(layer)) lastBase = index;
  });
  const after = layers.slice(lastBase + 1).find((layer) => layer.type === "symbol");
  return (after ?? firstSymbol)?.id;
}
