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

export type ReachMode = "walk" | "drive" | "transit";

/** The area reachable from a point (GET /isochrone), as a GeoJSON polygon. */
export interface Reach {
  mode: ReachMode;
  minutes: number;
  /** "network" = precomputed road network; "estimate" = straight-line circle. */
  method: "network" | "estimate";
  areaSqMi: number;
  geometry: AreaGeometry | null;
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
  /** Set on a locally ranked area whose name is still being looked up. */
  namePending?: boolean;
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

/** One turn of an "Ask Benri" conversation, as the API takes it. */
export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

/** What the user is looking at; the assistant's tools default to it. */
export interface ChatContext {
  address?: string;
  latitude?: number;
  longitude?: number;
  factors?: readonly FactorKey[];
  weights?: Readonly<Partial<Record<FactorKey, number>>>;
}

/** A place the assistant found, built by the API from tool output. */
export interface ChatResult {
  label: string;
  latitude: number;
  longitude: number;
  score?: number;
  weeklyMinutes?: number;
  why: string;
}

export interface ChatSource {
  tool: string;
  summary: string;
}

export interface ChatReply {
  reply: string;
  results: ChatResult[];
  sources: ChatSource[];
  /** True when the reply is a fallback summary or chat is paused. */
  limited: boolean;
}

/** One row of the data transparency page. */
export interface DataSource {
  id?: string;
  name: string;
  /** What in BenriSpace this source feeds. */
  feeds: string | null;
  license: string | null;
  licenseUrl: string | null;
  /** ISO timestamp of the last successful refresh. */
  lastUpdated: string | null;
}

/** What `POST /feedback` takes. */
export interface Feedback {
  kind: "summary" | "chat" | "place";
  /** What it is about: an address, a place name or a short excerpt. */
  target?: string;
  /** 1 thumbs up, -1 thumbs down, 0 or absent for a plain report. */
  rating?: -1 | 0 | 1;
  message?: string;
}
