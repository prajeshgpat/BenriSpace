import type { FactorKey } from "@/lib/api/types";

export type FactorGroup = "amenities" | "mobility" | "neighborhood";

export interface FactorMeta {
  label: string;
  description: string;
  group: FactorGroup;
  /** Counts toward the overall score but cannot be switched on or off. */
  underlying?: boolean;
}

export const FACTOR_GROUPS: Record<FactorGroup, string> = {
  amenities: "Daily amenities",
  mobility: "Getting around",
  neighborhood: "Neighborhood",
};

/**
 * Typed as a Record over the contract's keys so that adding or removing a
 * sub-score in openapi.yaml fails the typecheck until it is described here.
 * Every sub-score is already direction-adjusted by the API (higher is always
 * better), which is why the negative-signal factors say so explicitly.
 */
export const FACTORS: Record<FactorKey, FactorMeta> = {
  grocery: {
    label: "Grocery stores",
    description: "Supermarkets and grocers within walking distance.",
    group: "amenities",
  },
  gym: {
    label: "Gyms",
    description: "Fitness centers close by.",
    group: "amenities",
  },
  cafe: {
    label: "Cafes",
    description: "Coffee shops and cafes close by.",
    group: "amenities",
  },
  restaurant: {
    label: "Restaurants",
    description: "Restaurants within a short walk.",
    group: "amenities",
  },
  bar: {
    label: "Bars & pubs",
    description: "Bars, pubs and beer gardens within a short walk.",
    group: "amenities",
  },
  premiumRetail: {
    label: "Premium retail",
    description: "Whole Foods, Starbucks and Target nearby: a signal of a nicer area (Target counts for less).",
    group: "neighborhood",
    underlying: true,
  },
  transit: {
    label: "Public transit",
    description: "Subway, rail and bus stops within reach.",
    group: "mobility",
  },
  airport: {
    label: "Airport access",
    description: "Drive time to a major airport.",
    group: "mobility",
  },
  road: {
    label: "Road conditions",
    description: "Higher means fewer congestion-prone roads.",
    group: "mobility",
  },
  school: {
    label: "Schools",
    description: "How many schools are nearby, and how well they rate.",
    group: "neighborhood",
  },
  trailPopularity: {
    label: "Running route popularity",
    description: "Running trails and paths nearby.",
    group: "neighborhood",
    underlying: true,
  },
  gasStation: {
    label: "Gas stations",
    description: "Higher means fewer gas stations nearby.",
    group: "neighborhood",
  },
  convenienceStore: {
    label: "Convenience stores",
    description: "Higher means fewer convenience stores nearby.",
    group: "neighborhood",
  },
  emergencyCorridor: {
    label: "Noise corridor",
    description:
      "Main roads near fire stations, hospitals and police stations: where sirens and through-traffic noise are most likely.",
    group: "neighborhood",
  },
};

/** Every factor the API scores, including the underlying ones. */
export const ALL_FACTOR_KEYS = Object.keys(FACTORS) as FactorKey[];

/** Underlying metrics: counted in the overall score, never toggled in the UI. */
export const UNDERLYING_FACTOR_KEYS = ALL_FACTOR_KEYS.filter(
  (key) => FACTORS[key].underlying,
);

/** The user-facing, togglable factors (what the UI lists and counts). */
export const FACTOR_KEYS = ALL_FACTOR_KEYS.filter(
  (key) => !FACTORS[key].underlying,
);
