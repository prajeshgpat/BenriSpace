import type { ApiClient } from "@/lib/api/client";
import type { AreaScore, Explanation, Score, SubScores } from "@/lib/api/types";

export const GEO_ENTITY_ID = "21c5d4bd-e66e-423b-8f4c-8e569604f187";

/** Captured from the live API: every sub-score but one is null, and uses the pre-v1.4 keys. */
export const liveScoreBody = {
  geoEntityId: GEO_ENTITY_ID,
  address: "40.74920,-73.98500",
  latitude: 40.7492000000001,
  longitude: -73.9850000000001,
  compositeScore: 62.7906976744186,
  subScores: {
    grocery: null,
    gym: null,
    cafe: null,
    gasStation: null,
    convenienceStore: null,
    transit: null,
    school: null,
    road: null,
    emergencyCorridor: null,
    airport: 62.7906976744186,
  },
  weightsVersion: "v1-handtuned",
  computedAt: "2026-09-29T03:12:03.491922Z",
};

export const liveExplanationBody = {
  geoEntityId: GEO_ENTITY_ID,
  explanation:
    "This location's strongest factor is airport drive time (63/100).",
  computedAt: "2026-09-29T03:12:03.491922Z",
};

export const emptySubScores: SubScores = {
  grocery: null,
  restaurant: null,
  cafe: null,
  bar: null,
  gym: null,
  shopping: null,
  recreation: null,
  gasConvenience: null,
  transit: null,
  airport: null,
  traffic: null,
  school: null,
  emergencyCorridor: null,
};

export const fullSubScores: SubScores = {
  grocery: 91.4,
  restaurant: 80,
  cafe: 88.6,
  bar: 55,
  gym: 72,
  shopping: 70,
  recreation: 100,
  gasConvenience: 38,
  transit: 97,
  airport: 62.79,
  traffic: 22,
  school: 64.5,
  emergencyCorridor: 0,
};

export function makeScore(overrides: Partial<Score> = {}): Score {
  return {
    geoEntityId: GEO_ENTITY_ID,
    address: "40.74920,-73.98500",
    latitude: 40.7492,
    longitude: -73.985,
    compositeScore: 62.79,
    subScores: { ...emptySubScores, airport: 62.79 },
    weightsVersion: "v1-handtuned",
    computedAt: "2026-09-29T03:12:03.491922Z",
    precision: "grid",
    ...overrides,
  };
}

export function makeExplanation(
  overrides: Partial<Explanation> = {},
): Explanation {
  return { ...liveExplanationBody, ...overrides };
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** An ApiClient whose methods all reject, so a test only stubs what it exercises. */
export function stubClient(overrides: Partial<ApiClient> = {}): ApiClient {
  const unexpected = (name: string) => async () => {
    throw new Error(`Unexpected call to ${name}`);
  };
  return {
    getScore: unexpected("getScore"),
    getScoreByCoordinates: unexpected("getScoreByCoordinates"),
    getAreaByCoordinates: unexpected("getAreaByCoordinates"),
    getScoreExplanation: unexpected("getScoreExplanation"),
    getAreaExplanation: unexpected("getAreaExplanation"),
    getImprove: unexpected("getImprove"),
    getSimilar: unexpected("getSimilar"),
    getReach: unexpected("getReach"),
    suggestAddresses: unexpected("suggestAddresses"),
    reverseGeocode: unexpected("reverseGeocode"),
    getMapCells: unexpected("getMapCells"),
    getMapTop: unexpected("getMapTop"),
    chat: unexpected("chat"),
    getMapScores: unexpected("getMapScores"),
    getSources: unexpected("getSources"),
    sendFeedback: async () => {},
    ...overrides,
  };
}

export const AREA_RING: [number, number][] = [
  [-74.0, 40.72],
  [-73.99, 40.72],
  [-73.99, 40.73],
  [-74.0, 40.73],
  [-74.0, 40.72],
];

export function makeAreaScore(overrides: Partial<AreaScore> = {}): AreaScore {
  return {
    score: makeScore(),
    areaId: 42,
    area: {
      geometry: { type: "Polygon", coordinates: [AREA_RING] },
      areaSqMi: 0.35,
      boundedBy: ["Broadway", "Canal St", "Bowery", "Houston St"],
      cellCount: 3,
    },
    explanation: "This area's strongest factor is transit.",
    ...overrides,
  };
}

/** The wire shape of an `AreaScoreResponse`. */
export function makeAreaBody(overrides: Record<string, unknown> = {}) {
  const { score, area, areaId, explanation } = makeAreaScore();
  return { ...score, areaId, area, explanation, ...overrides };
}
