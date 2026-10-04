import type { components, operations } from "./schema";

type Schemas = components["schemas"];

/** The thirteen user-facing factors (scoring framework v1.4). Hand-written until the contract is regenerated. */
export const FACTOR_KEY_LIST = [
  "grocery",
  "restaurant",
  "cafe",
  "bar",
  "gym",
  "shopping",
  "recreation",
  "gasConvenience",
  "transit",
  "airport",
  "traffic",
  "school",
  "emergencyCorridor",
] as const;

export type FactorKey = (typeof FACTOR_KEY_LIST)[number];

/**
 * The contract types every sub-score as an optional number, but the live API
 * sends `null` for factors with no data in a grid cell and omits factors it
 * does not serve yet. The client normalises both cases to `null`, so every
 * key is always present here.
 */
export type SubScores = Record<FactorKey, number | null>;

export type Score = Omit<Schemas["ScoreResponse"], "subScores"> & {
  subScores: SubScores;
  /** e.g. "Park Slope, Brooklyn"; absent or null until the API names it. */
  neighborhood?: string | null;
};

export type SchoolInfo = NonNullable<Schemas["SchoolInfo"]>;

export type ExplanationSource = "ai" | "rules";

export type Explanation = Schemas["ExplanationResponse"] & {
  /** Who wrote the text; absent from older API responses. */
  source?: ExplanationSource;
};

/** The point-based explanation, which may be written by the LLM. */
export interface AreaExplanation {
  explanation: string;
  source: ExplanationSource;
  areaId: number | null;
  /** The factors the text was written for; empty when the API did not say. */
  priorities: FactorKey[];
}

export interface ImprovePlace {
  name: string;
  brand: string | null;
  distanceMi: number;
  distanceLabel: string;
  direction: string;
  latitude: number;
  longitude: number;
}

export interface ImproveBetterArea {
  latitude: number;
  longitude: number;
  direction: string;
  distanceMi: number;
  distanceLabel: string;
  factorScore: number;
  factorGain: number;
  compositeScore: number;
  compositeGain: number;
  neighborhood?: string | null;
}

export interface ImproveSuggestion {
  factor: FactorKey;
  label: string;
  score: number;
  places: ImprovePlace[];
  betterArea: ImproveBetterArea | null;
  tip: string;
}

export interface ImproveBestNearby {
  neighborhood?: string | null;
  latitude: number;
  longitude: number;
  direction: string;
  distanceLabel: string;
  compositeScore: number;
  compositeGain: number;
}

/** What would make the surrounding area score higher. */
export interface Improve {
  composite: number;
  radiusMi: number;
  suggestions: ImproveSuggestion[];
  bestNearby: ImproveBestNearby | null;
  priorities: FactorKey[];
}

/** The user's selection as the API takes it. `factors` is omitted for all 13. */
export interface PriorityQuery {
  factors?: readonly FactorKey[];
  weights?: Readonly<Partial<Record<FactorKey, number>>>;
}

export interface SimilarDifference {
  factor: FactorKey;
  label: string;
  /** Signed; positive means the similar area scores higher. */
  delta: number;
}

export interface SimilarArea {
  /** e.g. "Park Slope, Brooklyn"; null when unknown. */
  neighborhood?: string | null;
  latitude: number;
  longitude: number;
  direction: string;
  distanceLabel: string;
  /** 0 to 100. */
  similarity: number;
  compositeScore: number;
  areaLabel: string | null;
  differences: SimilarDifference[];
  summary: string;
}

export interface Similar {
  minSeparationMi: number;
  results: SimilarArea[];
  priorities: FactorKey[];
}

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
  neighborhood?: string | null;
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
