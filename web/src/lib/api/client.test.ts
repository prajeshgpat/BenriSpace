import { describe, expect, it, vi } from "vitest";

import { FACTOR_KEYS } from "@/lib/score/factors";
import {
  GEO_ENTITY_ID,
  jsonResponse,
  liveExplanationBody,
  liveScoreBody,
} from "@/test/fixtures";

import { createApiClient, normalizeSubScores, parseScore } from "./client";
import { ApiError } from "./errors";

const BASE_URL = "http://api.test/v1";

function clientReturning(response: Response | (() => Promise<Response>)) {
  const fetchMock = vi.fn<typeof fetch>(
    typeof response === "function" ? response : async () => response,
  );
  return { fetchMock, client: createApiClient({ baseUrl: BASE_URL, fetch: fetchMock }) };
}

async function rejection(promise: Promise<unknown>): Promise<ApiError> {
  const error = await promise.then(
    () => {
      throw new Error("Expected the request to be rejected.");
    },
    (cause: unknown) => cause,
  );
  expect(error).toBeInstanceOf(ApiError);
  return error as ApiError;
}

describe("getScore", () => {
  it("requests the score for a URL-encoded address without auth headers", async () => {
    const { client, fetchMock } = clientReturning(jsonResponse(liveScoreBody));

    await client.getScore("350 5th Ave, New York, NY & Co");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(
      `${BASE_URL}/score?address=350+5th+Ave%2C+New+York%2C+NY+%26+Co`,
    );
    const headers = new Headers(init?.headers);
    expect(headers.get("Accept")).toBe("application/json");
    expect(headers.has("Authorization")).toBe(false);
    expect(headers.has("X-API-Key")).toBe(false);
  });

  it("tolerates a trailing slash on the base URL", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => jsonResponse(liveScoreBody));
    const client = createApiClient({ baseUrl: `${BASE_URL}/`, fetch: fetchMock });

    await client.getScore("Hoboken");

    expect(fetchMock.mock.calls[0][0]).toBe(`${BASE_URL}/score?address=Hoboken`);
  });

  it("normalises null and absent sub-scores from a live response to null", async () => {
    const { client } = clientReturning(jsonResponse(liveScoreBody));

    const score = await client.getScore("350 5th Ave, New York, NY");

    expect(Object.keys(score.subScores).sort()).toEqual([...FACTOR_KEYS].sort());
    expect(score.subScores.airport).toBeCloseTo(62.79, 2);
    expect(score.subScores.grocery).toBeNull();
    // Missing from the payload altogether, not just null.
    expect(score.subScores.trailPopularity).toBeNull();
    expect(score.compositeScore).toBeCloseTo(62.79, 2);
    expect(score.weightsVersion).toBe("v1-handtuned");
  });

  it("keeps a genuine zero distinct from missing data", async () => {
    const body = {
      ...liveScoreBody,
      subScores: { ...liveScoreBody.subScores, grocery: 0 },
    };
    const { client } = clientReturning(jsonResponse(body));

    const score = await client.getScore("anywhere");

    expect(score.subScores.grocery).toBe(0);
    expect(score.subScores.gym).toBeNull();
  });

  it("maps a 404 to a not-found error carrying the API's code and message", async () => {
    const { client } = clientReturning(
      jsonResponse(
        {
          code: "not_found",
          message: "No geo entity within ingestion coverage for this location.",
          upgradeUrl: null,
        },
        404,
      ),
    );

    const error = await rejection(client.getScore("1600 Pennsylvania Ave"));

    expect(error.kind).toBe("not-found");
    expect(error.status).toBe(404);
    expect(error.code).toBe("not_found");
    expect(error.message).toMatch(/ingestion coverage/);
  });

  it("distinguishes an ungeocodable address from other bad requests", async () => {
    const unresolvable = clientReturning(
      jsonResponse({ code: "unresolvable_address", message: "Could not geocode" }, 400),
    );
    const invalid = clientReturning(
      jsonResponse({ code: "invalid_request", message: "Provide address" }, 400),
    );

    expect((await rejection(unresolvable.client.getScore("zzzz"))).kind).toBe(
      "unresolvable-address",
    );
    expect((await rejection(invalid.client.getScore("zzzz"))).kind).toBe(
      "invalid-request",
    );
  });

  it("treats FastAPI's 422 validation body as an invalid request", async () => {
    const { client } = clientReturning(
      jsonResponse({ detail: [{ type: "uuid_parsing", msg: "bad" }] }, 422),
    );

    const error = await rejection(client.getScore("zzzz"));

    expect(error.kind).toBe("invalid-request");
    expect(error.code).toBeUndefined();
    expect(error.message).toBe("Request failed with status 422.");
  });

  it("maps 5xx responses with a non-JSON body to a server error", async () => {
    const { client } = clientReturning(
      new Response("<html>Bad Gateway</html>", { status: 502 }),
    );

    const error = await rejection(client.getScore("zzzz"));

    expect(error.kind).toBe("server");
    expect(error.status).toBe(502);
  });

  it("maps a failed fetch to a network error", async () => {
    const cause = new TypeError("Failed to fetch");
    const { client } = clientReturning(async () => {
      throw cause;
    });

    const error = await rejection(client.getScore("zzzz"));

    expect(error.kind).toBe("network");
    expect(error.cause).toBe(cause);
  });

  it("maps an elapsed timeout to a timeout error", async () => {
    const fetchMock = vi.fn<typeof fetch>(
      (_input, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(init.signal?.reason),
          );
        }),
    );
    const client = createApiClient({ baseUrl: BASE_URL, fetch: fetchMock, timeoutMs: 5 });

    expect((await rejection(client.getScore("zzzz"))).kind).toBe("timeout");
  });

  it("propagates a caller's abort instead of reporting it as a failure", async () => {
    const controller = new AbortController();
    const fetchMock = vi.fn<typeof fetch>(
      (_input, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          );
        }),
    );
    const client = createApiClient({ baseUrl: BASE_URL, fetch: fetchMock });

    const pending = client.getScore("zzzz", { signal: controller.signal });
    controller.abort();

    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    await expect(pending).rejects.not.toBeInstanceOf(ApiError);
  });

  it.each([
    ["a non-object body", []],
    ["a missing composite score", { ...liveScoreBody, compositeScore: undefined }],
    ["a non-numeric composite score", { ...liveScoreBody, compositeScore: "63" }],
    ["a missing geo entity id", { ...liveScoreBody, geoEntityId: "" }],
  ])("rejects %s as an invalid response", async (_label, body) => {
    const { client } = clientReturning(jsonResponse(body));

    expect((await rejection(client.getScore("zzzz"))).kind).toBe("invalid-response");
  });
});

describe("getScoreExplanation", () => {
  it("requests the explanation for a geo entity", async () => {
    const { client, fetchMock } = clientReturning(jsonResponse(liveExplanationBody));

    const explanation = await client.getScoreExplanation(GEO_ENTITY_ID);

    expect(fetchMock.mock.calls[0][0]).toBe(
      `${BASE_URL}/score/${GEO_ENTITY_ID}/explanation`,
    );
    expect(explanation.explanation).toMatch(/airport drive time/);
  });

  it("maps a 404 to a not-found error", async () => {
    const { client } = clientReturning(
      jsonResponse({ code: "not_found", message: "No score on file." }, 404),
    );

    expect((await rejection(client.getScoreExplanation(GEO_ENTITY_ID))).kind).toBe(
      "not-found",
    );
  });

  it("rejects a body without explanation text", async () => {
    const { client } = clientReturning(jsonResponse({ geoEntityId: GEO_ENTITY_ID }));

    expect((await rejection(client.getScoreExplanation(GEO_ENTITY_ID))).kind).toBe(
      "invalid-response",
    );
  });
});

describe("normalizeSubScores", () => {
  it("returns every factor as null when sub-scores are missing entirely", () => {
    const normalized = normalizeSubScores(undefined);

    expect(Object.keys(normalized)).toHaveLength(FACTOR_KEYS.length);
    expect(Object.values(normalized).every((value) => value === null)).toBe(true);
  });

  it("discards non-finite and non-numeric values and unknown keys", () => {
    const normalized = normalizeSubScores({
      grocery: Number.NaN,
      gym: "80",
      cafe: 55,
      somethingNew: 12,
    });

    expect(normalized.grocery).toBeNull();
    expect(normalized.gym).toBeNull();
    expect(normalized.cafe).toBe(55);
    expect(normalized).not.toHaveProperty("somethingNew");
  });
});

describe("parseScore", () => {
  it("returns only contract fields", () => {
    const parsed = parseScore({ ...liveScoreBody, unexpected: true });

    expect(parsed).not.toHaveProperty("unexpected");
  });
});
