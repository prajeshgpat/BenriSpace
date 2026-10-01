import type { FactorKey } from "@/lib/api/types";

export type FactorGroup = "amenities" | "mobility" | "neighborhood";

export interface FactorMeta {
  label: string;
  description: string;
  group: FactorGroup;
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
    label: "Trails",
    description: "Popular running and walking trails nearby.",
    group: "neighborhood",
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
    label: "Emergency routes",
    description: "Higher means further from siren-heavy corridors.",
    group: "neighborhood",
  },
};

export const FACTOR_KEYS = Object.keys(FACTORS) as FactorKey[];
