import { describe, expect, it, vi } from "vitest";

import { ALL_FACTOR_KEYS } from "@/lib/score/factors";
import {
  GEO_ENTITY_ID,
  jsonResponse,
  liveExplanationBody,
  liveScoreBody,
  makeAreaBody,
} from "@/test/fixtures";

import {
  REVERSE_TIMEOUT_MS,
  SUGGEST_TIMEOUT_MS,
  createApiClient,
  normalizeSubScores,
  parseScore,
} from "./client";
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

    expect(Object.keys(score.subScores).sort()).toEqual([...ALL_FACTOR_KEYS].sort());
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

describe("getAreaExplanation", () => {
  it("requests the point explanation and parses it", async () => {
    const { client, fetchMock } = clientReturning(
      jsonResponse({ explanation: "Hi.", source: "ai", areaId: 3 }),
    );
    const result = await client.getAreaExplanation(40.7, -74);
    expect(fetchMock.mock.calls[0][0]).toBe(`${BASE_URL}/area/explanation?lat=40.7&lon=-74`);
    expect(result).toEqual({ explanation: "Hi.", source: "ai", areaId: 3 });
  });

  it("accepts a null areaId and rejects an unknown source", async () => {
    const ok = clientReturning(jsonResponse({ explanation: "x", source: "rules", areaId: null }));
    expect((await ok.client.getAreaExplanation(1, 2)).areaId).toBeNull();
    const bad = clientReturning(jsonResponse({ explanation: "x", source: "gpt", areaId: null }));
    expect((await rejection(bad.client.getAreaExplanation(1, 2))).kind).toBe("invalid-response");
  });
});

describe("normalizeSubScores", () => {
  it("returns every factor as null when sub-scores are missing entirely", () => {
    const normalized = normalizeSubScores(undefined);

    expect(Object.keys(normalized)).toHaveLength(ALL_FACTOR_KEYS.length);
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

describe("getScoreByCoordinates", () => {
  it("requests lat and lon, not an address", async () => {
    const { client, fetchMock } = clientReturning(jsonResponse(liveScoreBody));

    const score = await client.getScoreByCoordinates({ lat: 40.7484, lon: -73.9857 });

    expect(fetchMock.mock.calls[0][0]).toBe(`${BASE_URL}/score?lat=40.7484&lon=-73.9857`);
    expect(score.geoEntityId).toBe(GEO_ENTITY_ID);
  });

  it("maps a 404 to not-found", async () => {
    const { client } = clientReturning(jsonResponse({ code: "not_found", message: "none" }, 404));
    expect((await rejection(client.getScoreByCoordinates({ lat: 0, lon: 0 }))).kind).toBe("not-found");
  });
});

describe("suggestAddresses", () => {
  const body = {
    suggestions: [
      { label: "350 5th Avenue, New York, NY", latitude: 40.7484, longitude: -73.9857 },
      { label: "", latitude: 1, longitude: 2 },
      { label: "No coords" },
    ],
  };

  it("sends q and limit and keeps only well-formed suggestions", async () => {
    const { client, fetchMock } = clientReturning(jsonResponse(body));

    const result = await client.suggestAddresses("350 5th", { limit: 3 });

    expect(fetchMock.mock.calls[0][0]).toBe(`${BASE_URL}/suggest?q=350+5th&limit=3`);
    expect(result).toEqual([
      { label: "350 5th Avenue, New York, NY", latitude: 40.7484, longitude: -73.9857 },
    ]);
  });

  it("defaults the limit to 5", async () => {
    const { client, fetchMock } = clientReturning(jsonResponse({ suggestions: [] }));
    await client.suggestAddresses("abc");
    expect(String(fetchMock.mock.calls[0][0])).toContain("limit=5");
  });

  it("rejects a 503 so callers can degrade quietly", async () => {
    const { client } = clientReturning(
      jsonResponse({ code: "suggest_unavailable", message: "down" }, 503),
    );
    expect((await rejection(client.suggestAddresses("350 5th"))).kind).toBe("server");
  });

  it("rejects a malformed body", async () => {
    const { client } = clientReturning(jsonResponse({ nope: true }));
    expect((await rejection(client.suggestAddresses("350 5th"))).kind).toBe("invalid-response");
  });

  it("uses a timeout of its own, not the client-wide one", async () => {
    const timeout = vi.spyOn(AbortSignal, "timeout");
    const { client } = clientReturning(jsonResponse({ suggestions: [] }));

    await client.suggestAddresses("350 5th");

    expect(timeout).toHaveBeenCalledWith(SUGGEST_TIMEOUT_MS);
  });

  it("propagates a caller abort untouched", async () => {
    const controller = new AbortController();
    const fetchMock = vi.fn<typeof fetch>(
      (_url, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(init.signal?.reason));
        }),
    );
    const client = createApiClient({ baseUrl: BASE_URL, fetch: fetchMock });
    const pending = client.suggestAddresses("350 5th", { signal: controller.signal });
    controller.abort();
    await expect(pending).rejects.not.toBeInstanceOf(ApiError);
  });
});

describe("getMapCells", () => {
  const body = {
    precision: 6,
    factors: ["grocery", "transit"],
    weights: { grocery: 1.5, transit: 1.5 },
    weightsVersion: "v1-handtuned",
    count: 2,
    truncated: true,
    geohashes: ["dr5ru7", "dr5ru6"],
    scores: [88.1, 75],
  };

  it("builds the query from bbox, precision, factors, weights and limit", async () => {
    const { client, fetchMock } = clientReturning(jsonResponse(body));

    await client.getMapCells({
      bbox: [-74.05, 40.68, -73.85, 40.82],
      precision: 6,
      factors: ["grocery", "transit"],
      weights: { transit: 2 },
      limit: 12000,
    });

    const url = new URL(String(fetchMock.mock.calls[0][0]));
    expect(url.pathname).toBe("/v1/map/cells");
    expect(url.searchParams.get("bbox")).toBe("-74.05,40.68,-73.85,40.82");
    expect(url.searchParams.get("precision")).toBe("6");
    expect(url.searchParams.get("factors")).toBe("grocery,transit");
    expect(url.searchParams.get("weights")).toBe("transit:2");
    expect(url.searchParams.get("limit")).toBe("12000");
  });

  it("omits factors and weights when not given", async () => {
    const { client, fetchMock } = clientReturning(jsonResponse(body));
    await client.getMapCells({ bbox: [-75, 40, -74, 41], precision: 5 });
    const url = new URL(String(fetchMock.mock.calls[0][0]));
    expect(url.searchParams.has("factors")).toBe(false);
    expect(url.searchParams.has("weights")).toBe(false);
    expect(url.searchParams.get("precision")).toBe("5");
  });

  it("keeps the parallel arrays aligned and exposes truncated and weights", async () => {
    const { client } = clientReturning(jsonResponse(body));
    const cells = await client.getMapCells({ bbox: [-75, 40, -74, 41], precision: 6 });
    expect(cells.geohashes).toEqual(["dr5ru7", "dr5ru6"]);
    expect(cells.scores).toEqual([88.1, 75]);
    expect(cells.truncated).toBe(true);
    expect(cells.weights).toEqual({ grocery: 1.5, transit: 1.5 });
    expect(cells.factors).toEqual(["grocery", "transit"]);
  });

  it("drops a cell whose score is not a number but keeps the arrays aligned", async () => {
    const { client } = clientReturning(
      jsonResponse({ ...body, geohashes: ["a1", "dr5ru7", "dr5ru6"], scores: [null, 5, 6] }),
    );
    const cells = await client.getMapCells({ bbox: [-75, 40, -74, 41], precision: 6 });
    expect(cells.geohashes).toEqual(["dr5ru7", "dr5ru6"]);
    expect(cells.scores).toEqual([5, 6]);
  });

  it("rejects mismatched parallel arrays", async () => {
    const { client } = clientReturning(jsonResponse({ ...body, scores: [1] }));
    expect((await rejection(client.getMapCells({ bbox: [-75, 40, -74, 41], precision: 6 }))).kind).toBe(
      "invalid-response",
    );
  });

  it("maps 429 to rate-limited with Retry-After", async () => {
    const { client } = clientReturning(
      new Response(JSON.stringify({ code: "rate_limited", message: "slow" }), {
        status: 429,
        headers: { "Content-Type": "application/json", "Retry-After": "12" },
      }),
    );
    const error = await rejection(client.getMapCells({ bbox: [-75, 40, -74, 41], precision: 6 }));
    expect(error.kind).toBe("rate-limited");
    expect(error.retryAfterSeconds).toBe(12);
  });

  it("maps 400 to invalid-request", async () => {
    const { client } = clientReturning(jsonResponse({ code: "bad_bbox", message: "bad" }, 400));
    expect((await rejection(client.getMapCells({ bbox: [-75, 40, -74, 41], precision: 6 }))).kind).toBe(
      "invalid-request",
    );
  });
});

describe("getMapTop", () => {
  const body = {
    factors: ["grocery"],
    weights: { grocery: 1.5 },
    weightsVersion: "v1-handtuned",
    results: [
      {
        geohash: "dr5ru7",
        latitude: 40.7546,
        longitude: -73.985,
        score: 99.8,
        metroArea: "nyc",
        subScores: { grocery: 99.7, gym: null },
      },
      { geohash: "bad" },
    ],
  };

  it("builds the query and normalises sub-scores", async () => {
    const { client, fetchMock } = clientReturning(jsonResponse(body));

    const top = await client.getMapTop({
      bbox: [-74.05, 40.68, -73.85, 40.82],
      factors: ["grocery"],
      weights: { grocery: 3 },
      limit: 10,
      minSeparationMi: 0.6,
    });

    const url = new URL(String(fetchMock.mock.calls[0][0]));
    expect(url.pathname).toBe("/v1/map/top");
    expect(url.searchParams.get("bbox")).toBe("-74.05,40.68,-73.85,40.82");
    expect(url.searchParams.get("weights")).toBe("grocery:3");
    expect(url.searchParams.get("minSeparationMi")).toBe("0.6");
    expect(url.searchParams.has("minSeparationKm")).toBe(false);
    expect(top.results).toHaveLength(1);
    expect(top.results[0].subScores.grocery).toBe(99.7);
    expect(top.results[0].subScores.cafe).toBeNull();
    expect(top.results[0].metroArea).toBe("nyc");
  });

  it("has no bbox by default, meaning the whole metro", async () => {
    const { client, fetchMock } = clientReturning(jsonResponse(body));
    await client.getMapTop({});
    expect(String(fetchMock.mock.calls[0][0])).toBe(`${BASE_URL}/map/top?`);
  });

  it("rejects a body without results", async () => {
    const { client } = clientReturning(jsonResponse({ factors: [] }));
    expect((await rejection(client.getMapTop({}))).kind).toBe("invalid-response");
  });
});

describe("reverseGeocode", () => {
  const body = {
    label: "9 Journal Square Concourse, Jersey City, NJ",
    latitude: 40.7314,
    longitude: -74.0635,
  };

  it("sends lat and lon and returns the label", async () => {
    const { client, fetchMock } = clientReturning(jsonResponse(body));

    const result = await client.reverseGeocode({ lat: 40.7314, lon: -74.0635 });

    expect(fetchMock.mock.calls[0][0]).toBe(
      `${BASE_URL}/reverse?lat=40.7314&lon=-74.0635`,
    );
    expect(result).toEqual(body);
  });

  it("passes a null or blank label through as null", async () => {
    for (const label of [null, "  "]) {
      const { client } = clientReturning(jsonResponse({ ...body, label }));
      expect((await client.reverseGeocode({ lat: 1, lon: 2 })).label).toBeNull();
    }
  });

  it("rejects a malformed body as invalid-response", async () => {
    const { client } = clientReturning(jsonResponse({ label: 5 }));
    const error = await rejection(client.reverseGeocode({ lat: 1, lon: 2 }));
    expect(error.kind).toBe("invalid-response");
  });

  it("maps 422 out_of_coverage and 503 to rejections", async () => {
    const out = clientReturning(
      jsonResponse({ code: "out_of_coverage", message: "outside" }, 422),
    );
    expect((await rejection(out.client.reverseGeocode({ lat: 1, lon: 2 }))).kind).toBe(
      "invalid-request",
    );
    const down = clientReturning(
      jsonResponse({ code: "reverse_unavailable", message: "down" }, 503),
    );
    expect((await rejection(down.client.reverseGeocode({ lat: 1, lon: 2 }))).kind).toBe(
      "server",
    );
  });

  it("times out after REVERSE_TIMEOUT_MS and honours caller aborts", async () => {
    const timeoutSpy = vi.spyOn(AbortSignal, "timeout");
    const { client } = clientReturning(jsonResponse(body));
    await client.reverseGeocode({ lat: 1, lon: 2 });
    expect(timeoutSpy).toHaveBeenCalledWith(REVERSE_TIMEOUT_MS);
    timeoutSpy.mockRestore();

    const controller = new AbortController();
    const { client: aborting } = clientReturning(async () => {
      controller.abort();
      throw new DOMException("aborted", "AbortError");
    });
    await expect(
      aborting.reverseGeocode({ lat: 1, lon: 2 }, { signal: controller.signal }),
    ).rejects.toMatchObject({ name: "AbortError" });
  });
});

describe("parseScore school", () => {
  const base = {
    geoEntityId: "21c5d4bd-e66e-423b-8f4c-8e569604f187",
    address: "a",
    latitude: 1,
    longitude: 2,
    compositeScore: 50,
    subScores: {},
    weightsVersion: "v2",
    computedAt: "2026-09-29T03:12:03Z",
  };

  it("omits school when absent or null", () => {
    expect(parseScore(base).school).toBeUndefined();
    expect(parseScore({ ...base, school: null }).school).toBeUndefined();
  });

  it("keeps the school object", () => {
    const score = parseScore({
      ...base,
      school: { proximity: 60, ratingAvailable: false },
    });
    expect(score.school).toEqual({
      proximity: 60,
      ratingAvailable: false,
      districtName: null,
      source: null,
    });
  });
});

describe("getAreaByCoordinates", () => {
  it("requests /area with lat and lon and parses the polygon", async () => {
    const { client, fetchMock } = clientReturning(jsonResponse(makeAreaBody()));

    const result = await client.getAreaByCoordinates({ lat: 40.725, lon: -73.995 });

    expect(fetchMock.mock.calls[0][0]).toBe(`${BASE_URL}/area?lat=40.725&lon=-73.995`);
    expect(result.areaId).toBe(42);
    expect(result.score.geoEntityId).toBe(GEO_ENTITY_ID);
    expect(result.score.subScores.grocery).toBeNull();
    expect(result.area.geometry.type).toBe("Polygon");
    expect(result.area).toMatchObject({
      areaSqMi: 0.35,
      cellCount: 3,
      boundedBy: ["Broadway", "Canal St", "Bowery", "Houston St"],
    });
    expect(result.explanation).toMatch(/strongest factor/);
  });

  it("accepts a MultiPolygon", async () => {
    const ring = [[0, 0], [1, 0], [1, 1], [0, 0]];
    const { client } = clientReturning(
      jsonResponse(
        makeAreaBody({
          area: {
            geometry: { type: "MultiPolygon", coordinates: [[ring], [ring]] },
            areaSqMi: 1,
            boundedBy: [],
            cellCount: 2,
          },
        }),
      ),
    );

    const result = await client.getAreaByCoordinates({ lat: 0, lon: 0 });

    expect(result.area.geometry.type).toBe("MultiPolygon");
  });

  it.each([
    ["an unknown geometry type", { type: "Point", coordinates: [0, 0] }],
    ["an open ring", { type: "Polygon", coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1]]] }],
    ["too few positions", { type: "Polygon", coordinates: [[[0, 0], [1, 1], [0, 0]]] }],
    ["out-of-range coordinates", { type: "Polygon", coordinates: [[[0, 0], [200, 0], [1, 1], [0, 0]]] }],
    ["no coordinates", { type: "Polygon" }],
    ["an empty MultiPolygon", { type: "MultiPolygon", coordinates: [] }],
  ])("rejects %s as an invalid response", async (_label, geometry) => {
    const { client } = clientReturning(
      jsonResponse(
        makeAreaBody({
          area: { geometry, areaSqMi: 1, boundedBy: [], cellCount: 1 },
        }),
      ),
    );
    expect((await rejection(client.getAreaByCoordinates({ lat: 0, lon: 0 }))).kind).toBe(
      "invalid-response",
    );
  });

  it("rejects a body missing the area or explanation", async () => {
    const { client } = clientReturning(jsonResponse({ ...liveScoreBody, areaId: 1 }));
    expect((await rejection(client.getAreaByCoordinates({ lat: 0, lon: 0 }))).kind).toBe(
      "invalid-response",
    );
  });

  it("maps a 404 to not-found", async () => {
    const { client } = clientReturning(
      jsonResponse({ code: "area_not_found", message: "none" }, 404),
    );
    const error = await rejection(client.getAreaByCoordinates({ lat: 0, lon: 0 }));
    expect(error.kind).toBe("not-found");
    expect(error.code).toBe("area_not_found");
  });

  it("maps a 500 to a server error", async () => {
    const { client } = clientReturning(jsonResponse({ message: "boom" }, 500));
    expect((await rejection(client.getAreaByCoordinates({ lat: 0, lon: 0 }))).kind).toBe("server");
  });
});
