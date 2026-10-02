import type { components, operations } from "./schema";

type Schemas = components["schemas"];

export type FactorKey = keyof Schemas["SubScores"];

/**
 * The contract types every sub-score as an optional number, but the live API
 * sends `null` for factors with no data in a grid cell and omits factors it
 * does not serve yet. The client normalises both cases to `null`, so every
 * key is always present here.
 */
export type SubScores = Record<FactorKey, number | null>;

export type Score = Omit<Schemas["ScoreResponse"], "subScores"> & {
  subScores: SubScores;
};

export type SchoolInfo = NonNullable<Schemas["SchoolInfo"]>;

export type Explanation = Schemas["ExplanationResponse"];

export type ApiErrorBody = Schemas["Error"];

export type ScoreQuery = NonNullable<
  operations["getScore"]["parameters"]["query"]
>;

export type Suggestion = Schemas["Suggestion"];

/** `label` is null when the point has no usable address. */
export type ReverseGeocode = Schemas["ReverseResponse"];

export interface MapCells {
  precision: number;
  factors: FactorKey[];
  weights: Record<string, number>;
  weightsVersion: string;
  truncated: boolean;
  geohashes: string[];
  /** Composite 0-100 for `geohashes[i]`. */
  scores: number[];
}

export type MapTopResult = Omit<Schemas["MapTopResult"], "subScores"> & {
  subScores: SubScores;
};

export interface MapTop {
  factors: FactorKey[];
  weights: Record<string, number>;
  weightsVersion: string;
  results: MapTopResult[];
}

/** `[minLon, minLat, maxLon, maxLat]`. */
export type Bbox = readonly [number, number, number, number];

export interface MapCellsQuery {
  bbox: Bbox;
  precision: 5 | 6;
  factors?: readonly FactorKey[];
  weights?: Readonly<Partial<Record<FactorKey, number>>>;
  limit?: number;
}

export interface MapTopQuery {
  bbox?: Bbox;
  factors?: readonly FactorKey[];
  weights?: Readonly<Partial<Record<FactorKey, number>>>;
  limit?: number;
  /** Miles. The API rejects requests that send both units, so only this is sent. */
  minSeparationMi?: number;
}

/** GeoJSON position `[lon, lat]`. */
export type Position = readonly [number, number];

export type AreaGeometry =
  | { type: "Polygon"; coordinates: Position[][] }
  | { type: "MultiPolygon"; coordinates: Position[][][] };

export interface AreaInfo {
  geometry: AreaGeometry;
  areaSqMi: number;
  /** Up to four road names that form most of the boundary. */
  boundedBy: string[];
  /** Grid cells blended into the area's score. */
  cellCount: number;
}

/** A score for the secondary-road polygon around a point. */
export interface AreaScore {
  score: Score;
  areaId: number;
  area: AreaInfo;
  /** Plain-language "why this score", inline: no second request is needed. */
  explanation: string;
}
