import { ALL_FACTOR_KEYS } from "@/lib/score/factors";

import { ApiError } from "./errors";
import type {
  AreaGeometry,
  AreaInfo,
  AreaExplanation,
  AreaScore,
  Explanation,
  Improve,
  ImproveBestNearby,
  ImproveBetterArea,
  ImprovePlace,
  ImproveSuggestion,
  ExplanationSource,
  Position,
  FactorKey,
  MapCells,
  MapCellsQuery,
  MapTop,
  MapTopQuery,
  MapTopResult,
  ReverseGeocode,
  Score,
  ScoreQuery,
  Suggestion,
  SubScores,
  SchoolInfo,
} from "./types";

export const DEFAULT_TIMEOUT_MS = 20_000;

export interface ApiClientOptions {
  baseUrl: string;
  fetch?: typeof fetch;
  timeoutMs?: number;
}

export interface RequestOptions {
  signal?: AbortSignal;
  /** Overrides the client-wide timeout for this request. */
  timeoutMs?: number;
}

export interface Coordinates {
  lat: number;
  lon: number;
}

/** Autocomplete is a nicety; give up quickly rather than hold the UI. */
export const SUGGEST_TIMEOUT_MS = 10_000;

/** A readable address is decoration; give up quickly rather than hold the UI. */
export const REVERSE_TIMEOUT_MS = 8_000;

export interface ApiClient {
  getScore(address: string, options?: RequestOptions): Promise<Score>;
  getScoreByCoordinates(
    coordinates: Coordinates,
    options?: RequestOptions,
  ): Promise<Score>;
  /** Rejects with a `not-found` ApiError when no area polygon contains the point. */
  getAreaByCoordinates(
    coordinates: Coordinates,
    options?: RequestOptions,
  ): Promise<AreaScore>;
  suggestAddresses(
    query: string,
    options?: RequestOptions & { limit?: number },
  ): Promise<Suggestion[]>;
  reverseGeocode(
    coordinates: Coordinates,
    options?: RequestOptions,
  ): Promise<ReverseGeocode>;
  getMapCells(query: MapCellsQuery, options?: RequestOptions): Promise<MapCells>;
  getMapTop(query: MapTopQuery, options?: RequestOptions): Promise<MapTop>;
  getScoreExplanation(
    geoEntityId: string,
    options?: RequestOptions,
  ): Promise<Explanation>;
  /** Slower than `getAreaByCoordinates`: the text may be written by the LLM. */
  getAreaExplanation(
    lat: number,
    lon: number,
    signal?: AbortSignal,
  ): Promise<AreaExplanation>;
  /** What would raise the score nearby: named places and better spots. */
  getImprove(lat: number, lon: number, signal?: AbortSignal): Promise<Improve>;
}

type JsonObject = Record<string, unknown>;

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function invalidResponse(what: string): ApiError {
  return new ApiError("invalid-response", `Unexpected ${what} response shape.`);
}

export function normalizeSubScores(raw: unknown): SubScores {
  const source = isObject(raw) ? raw : {};
  return Object.fromEntries(
    ALL_FACTOR_KEYS.map((key) => {
      const value = source[key];
      return [key, isFiniteNumber(value) ? value : null];
    }),
  ) as SubScores;
}

function parseSchool(raw: unknown): { school?: SchoolInfo } {
  if (!isObject(raw) || typeof raw.ratingAvailable !== "boolean") return {};
  const text = (value: unknown) =>
    typeof value === "string" && value.trim() !== "" ? value : null;
  return {
    school: {
      proximity: isFiniteNumber(raw.proximity) ? raw.proximity : null,
      ratingAvailable: raw.ratingAvailable,
      districtName: text(raw.districtName),
      source: text(raw.source),
    },
  };
}

export function parseScore(body: unknown): Score {
  if (
    !isObject(body) ||
    !isNonEmptyString(body.geoEntityId) ||
    typeof body.address !== "string" ||
    !isFiniteNumber(body.latitude) ||
    !isFiniteNumber(body.longitude) ||
    !isFiniteNumber(body.compositeScore) ||
    typeof body.weightsVersion !== "string" ||
    typeof body.computedAt !== "string"
  ) {
    throw invalidResponse("score");
  }
  return {
    geoEntityId: body.geoEntityId,
    address: body.address,
    latitude: body.latitude,
    longitude: body.longitude,
    compositeScore: body.compositeScore,
    subScores: normalizeSubScores(body.subScores),
    weightsVersion: body.weightsVersion,
    computedAt: body.computedAt,
    ...parseSchool(body.school),
  };
}

function isPosition(value: unknown): value is Position {
  return (
    Array.isArray(value) &&
    value.length >= 2 &&
    isFiniteNumber(value[0]) &&
    isFiniteNumber(value[1]) &&
    Math.abs(value[0]) <= 180 &&
    Math.abs(value[1]) <= 90
  );
}

/** A linear ring: at least four positions, closed. */
function isRing(value: unknown): value is Position[] {
  if (!Array.isArray(value) || value.length < 4 || !value.every(isPosition)) {
    return false;
  }
  const first = value[0];
  const last = value[value.length - 1];
  return first[0] === last[0] && first[1] === last[1];
}

function isPolygonRings(value: unknown): value is Position[][] {
  return Array.isArray(value) && value.length > 0 && value.every(isRing);
}

function parseGeometry(raw: unknown): AreaGeometry {
  if (isObject(raw) && Array.isArray(raw.coordinates)) {
    if (raw.type === "Polygon" && isPolygonRings(raw.coordinates)) {
      return { type: "Polygon", coordinates: raw.coordinates };
    }
    if (
      raw.type === "MultiPolygon" &&
      raw.coordinates.length > 0 &&
      raw.coordinates.every(isPolygonRings)
    ) {
      return {
        type: "MultiPolygon",
        coordinates: raw.coordinates as Position[][][],
      };
    }
  }
  throw invalidResponse("area geometry");
}

export function parseAreaScore(body: unknown): AreaScore {
  if (
    !isObject(body) ||
    !isFiniteNumber(body.areaId) ||
    !isObject(body.area) ||
    !isFiniteNumber(body.area.areaSqMi) ||
    !isFiniteNumber(body.area.cellCount) ||
    typeof body.explanation !== "string"
  ) {
    throw invalidResponse("area");
  }
  const area: AreaInfo = {
    geometry: parseGeometry(body.area.geometry),
    areaSqMi: body.area.areaSqMi,
    boundedBy: Array.isArray(body.area.boundedBy)
      ? body.area.boundedBy.filter(isNonEmptyString)
      : [],
    cellCount: Math.max(1, Math.round(body.area.cellCount)),
  };
  return {
    score: parseScore(body),
    areaId: body.areaId,
    area,
    explanation: body.explanation,
  };
}

function parseSource(value: unknown): ExplanationSource | undefined {
  return value === "ai" || value === "rules" ? value : undefined;
}

export function parseAreaExplanation(body: unknown): AreaExplanation {
  if (
    !isObject(body) ||
    typeof body.explanation !== "string" ||
    (body.source !== "ai" && body.source !== "rules") ||
    !(body.areaId === null || isFiniteNumber(body.areaId))
  ) {
    throw invalidResponse("area explanation");
  }
  return {
    explanation: body.explanation,
    source: body.source,
    areaId: body.areaId,
  };
}

export function parseExplanation(body: unknown): Explanation {
  if (
    !isObject(body) ||
    !isNonEmptyString(body.geoEntityId) ||
    typeof body.explanation !== "string" ||
    typeof body.computedAt !== "string"
  ) {
    throw invalidResponse("explanation");
  }
  return {
    geoEntityId: body.geoEntityId,
    explanation: body.explanation,
    computedAt: body.computedAt,
    ...(parseSource(body.source) ? { source: parseSource(body.source) } : {}),
  };
}

function parsePlace(raw: unknown): ImprovePlace[] {
  if (
    !isObject(raw) ||
    !isNonEmptyString(raw.name) ||
    !isFiniteNumber(raw.distanceMi) ||
    typeof raw.distanceLabel !== "string" ||
    typeof raw.direction !== "string" ||
    !isFiniteNumber(raw.latitude) ||
    !isFiniteNumber(raw.longitude)
  ) {
    return [];
  }
  return [
    {
      name: raw.name,
      brand: isNonEmptyString(raw.brand) ? raw.brand : null,
      distanceMi: raw.distanceMi,
      distanceLabel: raw.distanceLabel,
      direction: raw.direction,
      latitude: raw.latitude,
      longitude: raw.longitude,
    },
  ];
}

function parseBetterArea(raw: unknown): ImproveBetterArea | null {
  if (
    !isObject(raw) ||
    !isFiniteNumber(raw.latitude) ||
    !isFiniteNumber(raw.longitude) ||
    typeof raw.direction !== "string" ||
    !isFiniteNumber(raw.distanceMi) ||
    typeof raw.distanceLabel !== "string" ||
    !isFiniteNumber(raw.factorScore) ||
    !isFiniteNumber(raw.factorGain) ||
    !isFiniteNumber(raw.compositeScore) ||
    !isFiniteNumber(raw.compositeGain)
  ) {
    return null;
  }
  return {
    latitude: raw.latitude,
    longitude: raw.longitude,
    direction: raw.direction,
    distanceMi: raw.distanceMi,
    distanceLabel: raw.distanceLabel,
    factorScore: raw.factorScore,
    factorGain: raw.factorGain,
    compositeScore: raw.compositeScore,
    compositeGain: raw.compositeGain,
  };
}

function parseBestNearby(raw: unknown): ImproveBestNearby | null {
  if (
    !isObject(raw) ||
    !isFiniteNumber(raw.latitude) ||
    !isFiniteNumber(raw.longitude) ||
    typeof raw.direction !== "string" ||
    typeof raw.distanceLabel !== "string" ||
    !isFiniteNumber(raw.compositeScore) ||
    !isFiniteNumber(raw.compositeGain)
  ) {
    return null;
  }
  return {
    latitude: raw.latitude,
    longitude: raw.longitude,
    direction: raw.direction,
    distanceLabel: raw.distanceLabel,
    compositeScore: raw.compositeScore,
    compositeGain: raw.compositeGain,
  };
}

export function parseImprove(body: unknown): Improve {
  if (
    !isObject(body) ||
    !isFiniteNumber(body.composite) ||
    !isFiniteNumber(body.radiusMi) ||
    !Array.isArray(body.suggestions)
  ) {
    throw invalidResponse("improve");
  }
  const suggestions = body.suggestions.flatMap((item): ImproveSuggestion[] =>
    isObject(item) &&
    isFactorKey(item.factor) &&
    isNonEmptyString(item.label) &&
    isFiniteNumber(item.score) &&
    typeof item.tip === "string"
      ? [
          {
            factor: item.factor,
            label: item.label,
            score: item.score,
            places: Array.isArray(item.places)
              ? item.places.flatMap(parsePlace)
              : [],
            betterArea: parseBetterArea(item.betterArea),
            tip: item.tip,
          },
        ]
      : [],
  );
  return {
    composite: body.composite,
    radiusMi: body.radiusMi,
    suggestions,
    bestNearby: parseBestNearby(body.bestNearby),
  };
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return undefined;
  }
}

const FACTOR_KEY_SET: ReadonlySet<string> = new Set(ALL_FACTOR_KEYS);

function isFactorKey(value: unknown): value is FactorKey {
  return typeof value === "string" && FACTOR_KEY_SET.has(value);
}

function parseWeights(raw: unknown): Record<string, number> {
  if (!isObject(raw)) return {};
  return Object.fromEntries(
    Object.entries(raw).filter(([, value]) => isFiniteNumber(value)),
  ) as Record<string, number>;
}

function parseFactors(raw: unknown): FactorKey[] {
  return Array.isArray(raw) ? raw.filter(isFactorKey) : [];
}

export function parseSuggestions(body: unknown): Suggestion[] {
  if (!isObject(body) || !Array.isArray(body.suggestions)) {
    throw invalidResponse("suggestions");
  }
  return body.suggestions.flatMap((item): Suggestion[] =>
    isObject(item) &&
    isNonEmptyString(item.label) &&
    isFiniteNumber(item.latitude) &&
    isFiniteNumber(item.longitude)
      ? [{ label: item.label, latitude: item.latitude, longitude: item.longitude }]
      : [],
  );
}

export function parseReverseGeocode(body: unknown): ReverseGeocode {
  if (
    !isObject(body) ||
    !isFiniteNumber(body.latitude) ||
    !isFiniteNumber(body.longitude) ||
    (body.label !== null && typeof body.label !== "string")
  ) {
    throw invalidResponse("reverse geocode");
  }
  // An empty string is as useless as null; normalise so callers test one thing.
  return {
    label: body.label === null || body.label.trim() === "" ? null : body.label,
    latitude: body.latitude,
    longitude: body.longitude,
  };
}

export function parseMapCells(body: unknown): MapCells {
  if (
    !isObject(body) ||
    !Array.isArray(body.geohashes) ||
    !Array.isArray(body.scores) ||
    body.geohashes.length !== body.scores.length ||
    typeof body.truncated !== "boolean"
  ) {
    throw invalidResponse("map cells");
  }
  const rawScores: unknown[] = body.scores;
  const geohashes: string[] = [];
  const scores: number[] = [];
  body.geohashes.forEach((hash: unknown, index) => {
    const score = rawScores[index];
    if (isNonEmptyString(hash) && isFiniteNumber(score)) {
      geohashes.push(hash);
      scores.push(score);
    }
  });
  return {
    precision: isFiniteNumber(body.precision) ? body.precision : 6,
    factors: parseFactors(body.factors),
    weights: parseWeights(body.weights),
    weightsVersion:
      typeof body.weightsVersion === "string" ? body.weightsVersion : "",
    truncated: body.truncated,
    geohashes,
    scores,
  };
}

export function parseMapTop(body: unknown): MapTop {
  if (!isObject(body) || !Array.isArray(body.results)) {
    throw invalidResponse("best areas");
  }
  const results = body.results.flatMap((item): MapTopResult[] =>
    isObject(item) &&
    isNonEmptyString(item.geohash) &&
    isFiniteNumber(item.latitude) &&
    isFiniteNumber(item.longitude) &&
    isFiniteNumber(item.score)
      ? [
          {
            geohash: item.geohash,
            latitude: item.latitude,
            longitude: item.longitude,
            score: item.score,
            metroArea: typeof item.metroArea === "string" ? item.metroArea : "",
            subScores: normalizeSubScores(item.subScores),
          },
        ]
      : [],
  );
  return {
    factors: parseFactors(body.factors),
    weights: parseWeights(body.weights),
    weightsVersion:
      typeof body.weightsVersion === "string" ? body.weightsVersion : "",
    results,
  };
}

function formatNumber(value: number): string {
  return String(Math.round(value * 1e5) / 1e5);
}

function mapParams(query: MapCellsQuery | MapTopQuery): URLSearchParams {
  const params = new URLSearchParams();
  if (query.bbox) params.set("bbox", query.bbox.map(formatNumber).join(","));
  if (query.factors) params.set("factors", query.factors.join(","));
  const weights = Object.entries(query.weights ?? {});
  if (weights.length > 0) {
    params.set("weights", weights.map(([k, v]) => `${k}:${formatNumber(v)}`).join(","));
  }
  return params;
}

function errorFromResponse(
  status: number,
  body: unknown,
  headers?: Headers,
): ApiError {
  const code = isObject(body) && typeof body.code === "string" ? body.code : undefined;
  const message =
    isObject(body) && typeof body.message === "string"
      ? body.message
      : `Request failed with status ${status}.`;
  const details = { status, code };

  if (status === 404) return new ApiError("not-found", message, details);
  if (status === 429) {
    const retryAfter = Number(headers?.get("Retry-After"));
    return new ApiError("rate-limited", message, {
      ...details,
      retryAfterSeconds:
        Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : undefined,
    });
  }
  if (status === 400 && code === "unresolvable_address") {
    return new ApiError("unresolvable-address", message, details);
  }
  // 422 is FastAPI's own validation failure; it carries `{detail}` rather
  // than the contract's `{code, message}`.
  if (status === 400 || status === 422) {
    return new ApiError("invalid-request", message, details);
  }
  return new ApiError("server", message, details);
}

export function createApiClient({
  baseUrl,
  fetch: fetchImpl = globalThis.fetch,
  timeoutMs = DEFAULT_TIMEOUT_MS,
}: ApiClientOptions): ApiClient {
  const root = baseUrl.replace(/\/+$/, "");

  async function getJson(
    path: string,
    { signal, timeoutMs: requestTimeoutMs }: RequestOptions = {},
  ): Promise<unknown> {
    const timeout = AbortSignal.timeout(requestTimeoutMs ?? timeoutMs);
    let response: Response;
    try {
      response = await fetchImpl(`${root}${path}`, {
        headers: { Accept: "application/json" },
        signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
      });
    } catch (cause) {
      // A caller-initiated abort is not a failure; let it propagate untouched.
      if (signal?.aborted) throw cause;
      if (timeout.aborted) {
        throw new ApiError("timeout", "The request timed out.", { cause });
      }
      throw new ApiError("network", "Could not reach the BenriSpace API.", {
        cause,
      });
    }

    const body = await readJson(response);
    if (!response.ok) throw errorFromResponse(response.status, body, response.headers);
    return body;
  }

  return {
    async getScore(address, options) {
      const query: ScoreQuery = { address };
      const params = new URLSearchParams(query as Record<string, string>);
      return parseScore(await getJson(`/score?${params}`, options));
    },

    async getScoreByCoordinates({ lat, lon }, options) {
      const params = new URLSearchParams({ lat: String(lat), lon: String(lon) });
      return parseScore(await getJson(`/score?${params}`, options));
    },

    async getAreaByCoordinates({ lat, lon }, options) {
      const params = new URLSearchParams({ lat: String(lat), lon: String(lon) });
      return parseAreaScore(await getJson(`/area?${params}`, options));
    },

    async getAreaExplanation(lat, lon, signal) {
      const params = new URLSearchParams({ lat: String(lat), lon: String(lon) });
      return parseAreaExplanation(
        await getJson(`/area/explanation?${params}`, { signal }),
      );
    },

    async getImprove(lat, lon, signal) {
      const params = new URLSearchParams({
        lat: String(lat),
        lon: String(lon),
        radiusMi: "1",
        maxSuggestions: "3",
      });
      return parseImprove(await getJson(`/improve?${params}`, { signal }));
    },

    async getScoreExplanation(geoEntityId, options) {
      const path = `/score/${encodeURIComponent(geoEntityId)}/explanation`;
      return parseExplanation(await getJson(path, options));
    },

    async suggestAddresses(query, { limit = 5, ...options } = {}) {
      const params = new URLSearchParams({ q: query, limit: String(limit) });
      return parseSuggestions(
        await getJson(`/suggest?${params}`, {
          timeoutMs: SUGGEST_TIMEOUT_MS,
          ...options,
        }),
      );
    },

    async reverseGeocode({ lat, lon }, options) {
      const params = new URLSearchParams({ lat: String(lat), lon: String(lon) });
      return parseReverseGeocode(
        await getJson(`/reverse?${params}`, {
          timeoutMs: REVERSE_TIMEOUT_MS,
          ...options,
        }),
      );
    },

    async getMapCells(query, options) {
      const params = mapParams(query);
      params.set("precision", String(query.precision));
      if (query.limit) params.set("limit", String(query.limit));
      return parseMapCells(await getJson(`/map/cells?${params}`, options));
    },

    async getMapTop(query, options) {
      const params = mapParams(query);
      if (query.limit) params.set("limit", String(query.limit));
      if (query.minSeparationMi !== undefined) {
        params.set("minSeparationMi", String(query.minSeparationMi));
      }
      return parseMapTop(await getJson(`/map/top?${params}`, options));
    },
  };
}
