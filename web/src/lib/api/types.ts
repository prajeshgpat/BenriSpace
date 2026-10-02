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

export type Explanation = Schemas["ExplanationResponse"];

export type ApiErrorBody = Schemas["Error"];

export type ScoreQuery = NonNullable<
  operations["getScore"]["parameters"]["query"]
>;

export type Suggestion = Schemas["Suggestion"];

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
  minSeparationKm?: number;
}
