/**
 * Retunes OpenFreeMap's stock `dark` style. As shipped, land (#0c0c0c to
 * #202020) and water (#1b1b1d) are nearly the same near-black, roads are
 * black ribbons and the park fill equals the woodland fill, so the cell overlay
 * floats over a map in which nothing can be told apart. Here water turns a
 * distinct navy, parks a subdued green, buildings and roads lighter greys with
 * an amber motorway, and the labels get stronger halos.
 *
 * Pure and defensive: layers are found by id / source-layer / type, missing
 * ones are skipped, and any failure returns the style untouched.
 */

interface StyleLayer {
  id: string;
  type: string;
  "source-layer"?: string;
  paint?: Record<string, unknown>;
  [key: string]: unknown;
}

interface StyleLike {
  layers?: StyleLayer[];
  [key: string]: unknown;
}

type Paint = Record<string, unknown>;

export const DARK_PALETTE = {
  land: "#1c1e22",
  landuse: "#212429",
  water: "#0f2d50",
  waterway: "#1b4a7a",
  waterLabel: "#8fbfee",
  waterLabelHalo: "#0a2038",
  park: "#1d3325",
  building: "#2c3037",
  buildingOutline: "#3a3f48",
  roadMinor: "#363a41",
  roadPath: "#464b53",
  roadMajor: "#5c616a",
  roadCasing: "#121316",
  motorway: "#a9803f",
  motorwayCasing: "#2a2012",
  rail: "#3b3f47",
  aero: "#2a2d33",
  label: "#b4bac4",
  labelHalo: "rgba(10, 12, 15, 0.92)",
  roadLabel: "#9aa1ac",
} as const;

const P = DARK_PALETTE;

interface Rule {
  match: (layer: StyleLayer) => boolean;
  paint: Paint;
}

const idIs =
  (...ids: string[]) =>
  (layer: StyleLayer) =>
    ids.includes(layer.id);
const typeIn =
  (type: string, ...sourceLayers: string[]) =>
  (layer: StyleLayer) =>
    layer.type === type && sourceLayers.includes(layer["source-layer"] ?? "");

// First matching rule wins, so specific ids precede source-layer catch-alls.
const RULES: Rule[] = [
  {
    match: (l) => l.type === "background",
    paint: { "background-color": P.land },
  },
  { match: idIs("water"), paint: { "fill-color": P.water } },
  { match: idIs("waterway"), paint: { "line-color": P.waterway } },
  {
    match: typeIn("symbol", "water_name"),
    paint: {
      "text-color": P.waterLabel,
      "text-halo-color": P.waterLabelHalo,
      "text-halo-width": 1.4,
    },
  },
  {
    match: (l) =>
      l.type === "fill" &&
      (l["source-layer"] === "park" ||
        l.id === "landuse_park" ||
        l.id === "landcover_wood" ||
        l.id === "landcover_grass"),
    // The stock wood layer paints a texture that would hide the colour.
    paint: {
      "fill-color": P.park,
      "fill-opacity": 0.9,
      "fill-pattern": undefined,
    },
  },
  {
    match: idIs("landuse_residential"),
    paint: { "fill-color": P.landuse, "fill-opacity": 0.7 },
  },
  {
    match: typeIn("fill", "building"),
    paint: {
      "fill-color": P.building,
      "fill-outline-color": P.buildingOutline,
    },
  },
  { match: idIs("aeroway-area"), paint: { "fill-color": P.aero } },
  { match: idIs("aeroway-taxiway"), paint: { "line-color": P.roadMinor } },
  {
    match: idIs("aeroway-runway"),
    paint: { "line-color": P.roadMajor },
  },
  {
    match: idIs("aeroway-runway-casing"),
    paint: { "line-color": P.roadCasing },
  },
  { match: idIs("road_area_pier"), paint: { "fill-color": P.landuse } },
  { match: idIs("road_pier"), paint: { "line-color": P.roadMinor } },
  { match: idIs("highway_path"), paint: { "line-color": P.roadPath } },
  { match: idIs("highway_minor"), paint: { "line-color": P.roadMinor } },
  {
    match: idIs("highway_major_casing", "highway_motorway_casing"),
    paint: { "line-color": P.roadCasing },
  },
  { match: idIs("highway_major_inner"), paint: { "line-color": P.roadMajor } },
  {
    match: idIs("highway_major_subtle"),
    paint: { "line-color": P.roadMinor },
  },
  {
    match: idIs("highway_motorway_inner"),
    paint: { "line-color": P.motorway },
  },
  {
    match: idIs("highway_motorway_subtle"),
    paint: { "line-color": P.motorway },
  },
  {
    match: typeIn("line", "transportation"),
    paint: { "line-color": P.rail },
  },
  {
    match: typeIn("symbol", "transportation_name"),
    paint: {
      "text-color": P.roadLabel,
      "text-halo-color": P.labelHalo,
      "text-halo-width": 1.2,
      "text-halo-blur": 0,
    },
  },
  {
    match: typeIn("symbol", "place"),
    paint: {
      "text-color": P.label,
      "text-halo-color": P.labelHalo,
      "text-halo-width": 1.6,
    },
  },
];

// Railway dashes must keep the land colour so the gaps read as gaps.
const RAIL_DASH_PAINT: Paint = { "line-color": P.land };

function paintFor(layer: StyleLayer): Paint | null {
  if (/^railway.*dashline$/.test(layer.id)) return RAIL_DASH_PAINT;
  for (const rule of RULES) if (rule.match(layer)) return rule.paint;
  return null;
}

export function tuneDarkStyle<T>(style: T): T {
  try {
    const source = style as unknown as StyleLike;
    if (!source || !Array.isArray(source.layers)) return style;
    const layers = source.layers.map((layer) => {
      if (!layer || typeof layer !== "object" || typeof layer.id !== "string") {
        return layer;
      }
      const paint = paintFor(layer);
      if (!paint) return layer;
      const merged: Paint = { ...(layer.paint ?? {}), ...paint };
      for (const key of Object.keys(merged)) {
        if (merged[key] === undefined) delete merged[key];
      }
      return { ...layer, paint: merged };
    });
    return { ...source, layers } as unknown as T;
  } catch {
    return style;
  }
}
