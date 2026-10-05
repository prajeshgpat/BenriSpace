import { SCORE_PRECISION, type ScorePrecision } from "@/lib/config";
import {
  ALL_FACTOR_KEYS,
  LEGACY_FACTOR_ALIASES,
  canonicalFactorKey,
} from "@/lib/score/factors";

import { ApiError } from "./errors";
import type {
  AreaGeometry,
  AreaInfo,
  AreaExplanation,
  AreaScore,
  ChatContext,
  ChatReply,
  ChatResult,
  ChatTurn,
  DataSource,
  Explanation,
  Feedback,
  Improve,
  ImproveBestNearby,
  ImproveBetterArea,
  ImprovePlace,
  ImproveSuggestion,
  ExplanationSource,
  Position,
  PriorityQuery,
  Reach,
  ReachMode,
  Similar,
  SimilarArea,
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
  /** `point` adds `precision=point` to /score and /area; defaults to NEXT_PUBLIC_SCORE_PRECISION. */
  scorePrecision?: ScorePrecision;
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

/** A chat answer can take several tool calls on the server. */
export const CHAT_TIMEOUT_MS = 28_000;
/** The API reads only the most recent turns, each cut to this length. */
export const CHAT_MAX_TURNS = 6;
export const CHAT_MAX_CHARS = 2000;

/** The score file is about 1 MB; allow a slow connection. */
export const MAP_SCORES_TIMEOUT_MS = 30_000;

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
    options?: RequestOptions & PriorityQuery,
  ): Promise<Explanation>;
  /** Slower than `getAreaByCoordinates`: the text may be written by the LLM. */
  getAreaExplanation(
    lat: number,
    lon: number,
    options?: RequestOptions & PriorityQuery,
  ): Promise<AreaExplanation>;
  /** What would raise the score nearby: named places and better spots. */
  getImprove(
    lat: number,
    lon: number,
    options?: RequestOptions & PriorityQuery,
  ): Promise<Improve>;
  /** Areas elsewhere in the metro with a similar profile for the selected factors. */
  getSimilar(
    lat: number,
    lon: number,
    options?: RequestOptions & PriorityQuery,
  ): Promise<Similar>;
  /** The area reachable from a point within `minutes` by walking, driving or rail. */
  getReach(
    lat: number,
    lon: number,
    mode: ReachMode,
    minutes: number,
    options?: RequestOptions,
  ): Promise<Reach>;
  /** The compact all-cells score file (see `lib/scores/matrix.ts`). */
  getMapScores(options?: RequestOptions): Promise<ArrayBuffer>;
  /** Where the data comes from: names, licences and when each was last refreshed. */
  getSources(options?: RequestOptions): Promise<DataSource[]>;
  /** Thumbs and "wrong place" reports. Callers ignore failures. */
  sendFeedback(feedback: Feedback, options?: RequestOptions): Promise<void>;
  /** "Ask Benri": send the conversation so far; it must end with a user turn. */
  chat(
    messages: readonly ChatTurn[],
    context?: ChatContext,
    options?: RequestOptions,
  ): Promise<ChatReply>;
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
      if (isFiniteNumber(value)) return [key, value];
      // Old rows still carry the pre-v1.4 keys; fold them into the new pill.
      const legacy = Object.entries(LEGACY_FACTOR_ALIASES)
        .filter(([, target]) => target === key)
        .map(([old]) => source[old])
        .filter(isFiniteNumber);
      return [
        key,
        legacy.length > 0
          ? legacy.reduce((sum, n) => sum + n, 0) / legacy.length
          : null,
      ];
    }),
  ) as SubScores;
}

/** A neighborhood name, or null when absent or blank. */
function parseNeighborhood(raw: unknown): string | null {
  return typeof raw === "string" && raw.trim() !== "" ? raw.trim() : null;
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
    neighborhood: parseNeighborhood(body.neighborhood),
    precision: body.precision === "point" ? "point" : "grid",
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

export function parseReach(body: unknown): Reach {
  const iso = isObject(body) && isObject(body.isochrone) ? body.isochrone : null;
  if (
    !iso ||
    !isFiniteNumber(iso.minutes) ||
    !isFiniteNumber(iso.areaSqMi) ||
    (iso.mode !== "walk" && iso.mode !== "drive" && iso.mode !== "transit") ||
    (iso.method !== "network" && iso.method !== "estimate")
  ) {
    throw invalidResponse("reachable area");
  }
  return {
    mode: iso.mode,
    minutes: iso.minutes,
    method: iso.method,
    areaSqMi: iso.areaSqMi,
    geometry: iso.geometry ? parseGeometry(iso.geometry) : null,
  };
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
    priorities: parseFactors(body.priorities),
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
    neighborhood: parseNeighborhood(raw.neighborhood),
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
    neighborhood: parseNeighborhood(raw.neighborhood),
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
            factor: canonicalFactorKey(item.factor) ?? "grocery",
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
    priorities: parseFactors(body.priorities),
  };
}

export function parseSimilar(body: unknown): Similar {
  if (!isObject(body) || !Array.isArray(body.results)) {
    throw invalidResponse("similar areas");
  }
  const results = body.results.flatMap((item): SimilarArea[] =>
    isObject(item) &&
    isFiniteNumber(item.latitude) &&
    isFiniteNumber(item.longitude) &&
    typeof item.direction === "string" &&
    typeof item.distanceLabel === "string" &&
    isFiniteNumber(item.similarity) &&
    isFiniteNumber(item.compositeScore)
      ? [
          {
            latitude: item.latitude,
            longitude: item.longitude,
            direction: item.direction,
            distanceLabel: item.distanceLabel,
            similarity: item.similarity,
            compositeScore: item.compositeScore,
            areaLabel: isNonEmptyString(item.areaLabel) ? item.areaLabel : null,
            neighborhood: parseNeighborhood(item.neighborhood),
            differences: Array.isArray(item.differences)
              ? item.differences.flatMap((d): SimilarArea["differences"] =>
                  isObject(d) &&
                  isFactorKey(d.factor) &&
                  isNonEmptyString(d.label) &&
                  isFiniteNumber(d.delta)
                    ? [{ factor: canonicalFactorKey(d.factor) ?? "grocery", label: d.label, delta: d.delta }]
                    : [],
                )
              : [],
            summary: typeof item.summary === "string" ? item.summary : "",
          },
        ]
      : [],
  );
  return {
    minSeparationMi: isFiniteNumber(body.minSeparationMi)
      ? body.minSeparationMi
      : 0,
    results,
    priorities: parseFactors(body.priorities),
  };
}

export function parseChatReply(body: unknown): ChatReply {
  if (!isObject(body) || !isNonEmptyString(body.reply)) {
    throw invalidResponse("chat");
  }
  const results = Array.isArray(body.results)
    ? body.results.flatMap((item): ChatResult[] =>
        isObject(item) &&
        isNonEmptyString(item.label) &&
        isFiniteNumber(item.latitude) &&
        isFiniteNumber(item.longitude) &&
        typeof item.why === "string"
          ? [
              {
                label: item.label,
                latitude: item.latitude,
                longitude: item.longitude,
                why: item.why,
                ...(isFiniteNumber(item.score) ? { score: item.score } : {}),
                ...(isFiniteNumber(item.weeklyMinutes)
                  ? { weeklyMinutes: item.weeklyMinutes }
                  : {}),
              },
            ]
          : [],
      )
    : [];
  const sources = Array.isArray(body.sources)
    ? body.sources.flatMap((item) =>
        isObject(item) && isNonEmptyString(item.tool) && typeof item.summary === "string"
          ? [{ tool: item.tool, summary: item.summary }]
          : [],
      )
    : [];
  return {
    reply: body.reply,
    results: results.slice(0, 3),
    sources,
    limited: body.limited === true,
  };
}

/** The turns the API will read: the last few, trimmed, starting with the user. */
export function prepareChatTurns(messages: readonly ChatTurn[]): ChatTurn[] {
  const turns = messages
    .slice(-CHAT_MAX_TURNS)
    .map((m) => ({ role: m.role, content: m.content.trim().slice(0, CHAT_MAX_CHARS) }))
    .filter((m) => m.content !== "");
  while (turns.length > 0 && turns[0].role !== "user") turns.shift();
  if (turns.length === 0 || turns[turns.length - 1].role !== "user") {
    throw new ApiError("invalid-request", "Ask a question to start the chat.");
  }
  return turns;
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return undefined;
  }
}

/** True for a current key or a legacy alias; use `canonicalFactorKey` to read it. */
function isFactorKey(value: unknown): value is FactorKey {
  return canonicalFactorKey(value) !== null;
}

function parseWeights(raw: unknown): Record<string, number> {
  if (!isObject(raw)) return {};
  const weights: Record<string, number> = {};
  // Current keys win over any legacy alias that maps to the same pill.
  for (const legacyPass of [true, false]) {
    for (const [key, value] of Object.entries(raw)) {
      if (!isFiniteNumber(value)) continue;
      const canonical = canonicalFactorKey(key);
      if (legacyPass ? canonical !== null && canonical !== key : canonical === key) {
        weights[canonical ?? key] = value;
      }
    }
  }
  return weights;
}

function parseFactors(raw: unknown): FactorKey[] {
  if (!Array.isArray(raw)) return [];
  const keys = raw.flatMap((item) => canonicalFactorKey(item) ?? []);
  return [...new Set(keys)];
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
            neighborhood: parseNeighborhood(item.neighborhood),
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

export function parseSources(body: unknown): DataSource[] {
  const list = isObject(body) ? body.sources : body;
  if (!Array.isArray(list)) throw invalidResponse("data sources");
  const text = (value: unknown) =>
    typeof value === "string" && value.trim() !== "" ? value.trim() : null;
  return list.flatMap((item): DataSource[] => {
    if (!isObject(item)) return [];
    const name = text(item.name) ?? text(item.source);
    if (!name) return [];
    const link = text(item.licenseUrl) ?? text(item.licenceUrl) ?? text(item.url);
    return [
      {
        name,
        feeds:
          text(item.feeds) ?? text(item.description) ?? text(item.usedFor),
        license: text(item.license) ?? text(item.licence),
        licenseUrl: link && /^https?:\/\//i.test(link) ? link : null,
        lastUpdated:
          text(item.lastUpdated) ??
          text(item.lastRunAt) ??
          text(item.updatedAt),
      },
    ];
  });
}

function formatNumber(value: number): string {
  return String(Math.round(value * 1e5) / 1e5);
}

function mapParams(query: MapCellsQuery | MapTopQuery): URLSearchParams {
  const params = new URLSearchParams();
  if (query.bbox) params.set("bbox", query.bbox.map(formatNumber).join(","));
  return priorityParams(query, params);
}

/** `factors` and `weights`, shared by every endpoint that takes the user's selection. */
function priorityParams(
  query: PriorityQuery,
  params: URLSearchParams,
): URLSearchParams {
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
  scorePrecision = SCORE_PRECISION,
}: ApiClientOptions): ApiClient {
  const root = baseUrl.replace(/\/+$/, "");
  const withPrecision = (params: URLSearchParams) => {
    if (scorePrecision === "point") params.set("precision", "point");
    return params;
  };

  async function requestJson(
    path: string,
    init: { method: "GET" } | { method: "POST"; body: unknown },
    { signal, timeoutMs: requestTimeoutMs }: RequestOptions = {},
  ): Promise<unknown> {
    const timeout = AbortSignal.timeout(requestTimeoutMs ?? timeoutMs);
    let response: Response;
    try {
      response = await fetchImpl(`${root}${path}`, {
        headers:
          init.method === "POST"
            ? { Accept: "application/json", "Content-Type": "application/json" }
            : { Accept: "application/json" },
        ...(init.method === "POST"
          ? { method: "POST", body: JSON.stringify(init.body) }
          : {}),
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

  const getJson = (path: string, options?: RequestOptions) =>
    requestJson(path, { method: "GET" }, options);

  return {
    async getScore(address, options) {
      const query: ScoreQuery = { address };
      const params = withPrecision(new URLSearchParams(query as Record<string, string>));
      return parseScore(await getJson(`/score?${params}`, options));
    },

    async getScoreByCoordinates({ lat, lon }, options) {
      const params = withPrecision(
        new URLSearchParams({ lat: String(lat), lon: String(lon) }),
      );
      return parseScore(await getJson(`/score?${params}`, options));
    },

    async getAreaByCoordinates({ lat, lon }, options) {
      const params = withPrecision(
        new URLSearchParams({ lat: String(lat), lon: String(lon) }),
      );
      return parseAreaScore(await getJson(`/area?${params}`, options));
    },

    async getAreaExplanation(lat, lon, { factors, weights, ...options } = {}) {
      const params = priorityParams(
        { factors, weights },
        new URLSearchParams({ lat: String(lat), lon: String(lon) }),
      );
      return parseAreaExplanation(
        await getJson(`/area/explanation?${params}`, options),
      );
    },

    async getImprove(lat, lon, { factors, weights, ...options } = {}) {
      const params = priorityParams(
        { factors, weights },
        new URLSearchParams({
          lat: String(lat),
          lon: String(lon),
          radiusMi: "1",
          maxSuggestions: "3",
        }),
      );
      return parseImprove(await getJson(`/improve?${params}`, options));
    },

    async getSimilar(lat, lon, { factors, weights, ...options } = {}) {
      const params = priorityParams(
        { factors, weights },
        new URLSearchParams({
          lat: String(lat),
          lon: String(lon),
          k: "5",
          minSeparationMi: "1",
        }),
      );
      return parseSimilar(await getJson(`/similar?${params}`, options));
    },

    async getReach(lat, lon, mode, minutes, options) {
      const params = new URLSearchParams({
        lat: String(lat),
        lon: String(lon),
        mode,
        minutes: String(minutes),
      });
      return parseReach(await getJson(`/isochrone?${params}`, options));
    },

    async getScoreExplanation(geoEntityId, { factors, weights, ...options } = {}) {
      const params = priorityParams(
        { factors, weights },
        new URLSearchParams(),
      );
      const query = params.size > 0 ? `?${params}` : "";
      const path = `/score/${encodeURIComponent(geoEntityId)}/explanation${query}`;
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

    async getMapScores(options) {
      const timeout = AbortSignal.timeout(options?.timeoutMs ?? MAP_SCORES_TIMEOUT_MS);
      let response: Response;
      try {
        response = await fetchImpl(`${root}/map/scores`, {
          headers: { Accept: "application/octet-stream" },
          signal: options?.signal
            ? AbortSignal.any([options.signal, timeout])
            : timeout,
        });
      } catch (cause) {
        if (options?.signal?.aborted) throw cause;
        throw new ApiError(
          timeout.aborted ? "timeout" : "network",
          "Could not load the score file.",
          { cause },
        );
      }
      if (!response.ok) throw errorFromResponse(response.status, null, response.headers);
      return response.arrayBuffer();
    },

    async getSources(options) {
      return parseSources(await getJson("/sources", options));
    },

    async sendFeedback(feedback, options) {
      await requestJson("/feedback", { method: "POST", body: feedback }, options);
    },

    async chat(messages, context = {}, options) {
      const turns = prepareChatTurns(messages);
      const body: Record<string, unknown> = { messages: turns };
      if (Object.keys(context).length > 0) body.context = context;
      return parseChatReply(
        await requestJson(
          "/chat",
          { method: "POST", body },
          { timeoutMs: CHAT_TIMEOUT_MS, ...options },
        ),
      );
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
