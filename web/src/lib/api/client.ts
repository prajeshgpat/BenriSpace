import { FACTOR_KEYS } from "@/lib/score/factors";

import { ApiError } from "./errors";
import type { Explanation, Score, ScoreQuery, SubScores } from "./types";

export const DEFAULT_TIMEOUT_MS = 20_000;

export interface ApiClientOptions {
  baseUrl: string;
  fetch?: typeof fetch;
  timeoutMs?: number;
}

export interface RequestOptions {
  signal?: AbortSignal;
}

export interface ApiClient {
  getScore(address: string, options?: RequestOptions): Promise<Score>;
  getScoreExplanation(
    geoEntityId: string,
    options?: RequestOptions,
  ): Promise<Explanation>;
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
    FACTOR_KEYS.map((key) => {
      const value = source[key];
      return [key, isFiniteNumber(value) ? value : null];
    }),
  ) as SubScores;
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
  };
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return undefined;
  }
}

function errorFromResponse(status: number, body: unknown): ApiError {
  const code = isObject(body) && typeof body.code === "string" ? body.code : undefined;
  const message =
    isObject(body) && typeof body.message === "string"
      ? body.message
      : `Request failed with status ${status}.`;
  const details = { status, code };

  if (status === 404) return new ApiError("not-found", message, details);
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

  async function getJson(path: string, signal?: AbortSignal): Promise<unknown> {
    const timeout = AbortSignal.timeout(timeoutMs);
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
    if (!response.ok) throw errorFromResponse(response.status, body);
    return body;
  }

  return {
    async getScore(address, options) {
      const query: ScoreQuery = { address };
      const params = new URLSearchParams(query as Record<string, string>);
      return parseScore(await getJson(`/score?${params}`, options?.signal));
    },

    async getScoreExplanation(geoEntityId, options) {
      const path = `/score/${encodeURIComponent(geoEntityId)}/explanation`;
      return parseExplanation(await getJson(path, options?.signal));
    },
  };
}
