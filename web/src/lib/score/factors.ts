import { FACTOR_KEY_LIST, type FactorKey } from "@/lib/api/types";

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
 * factor fails the typecheck until it is described here. Every sub-score is
 * already direction-adjusted by the API (higher is always better), which is
 * why the negative-signal factors say so explicitly. Key order is the display
 * order within each group.
 */
export const FACTORS: Record<FactorKey, FactorMeta> = {
  grocery: {
    label: "Groceries",
    description: "Supermarkets and grocers within walking distance.",
    group: "amenities",
  },
  restaurant: {
    label: "Restaurants",
    description: "Restaurants within a short walk.",
    group: "amenities",
  },
  cafe: {
    label: "Cafes",
    description: "Coffee shops and cafes close by.",
    group: "amenities",
  },
  bar: {
    label: "Bars",
    description: "Bars, pubs and beer gardens within a short walk.",
    group: "amenities",
  },
  gym: {
    label: "Gym",
    description: "Fitness centers close by.",
    group: "amenities",
  },
  shopping: {
    label: "Shopping",
    description: "Department stores, malls and everyday retail nearby, a signal of a nicer area.",
    group: "amenities",
  },
  transit: {
    label: "Public transit",
    description: "Subway, rail and bus stops within reach.",
    group: "mobility",
  },
  airport: {
    label: "Airport",
    description: "Drive time to a major airport.",
    group: "mobility",
  },
  gasConvenience: {
    label: "Gas & Convenience",
    description: "Fuel and quick-stop stores nearby.",
    group: "mobility",
  },
  traffic: {
    label: "Traffic",
    description: "Fewer busy roads nearby.",
    group: "mobility",
  },
  school: {
    label: "Schools",
    description: "How many schools are nearby, and how well they rate.",
    group: "neighborhood",
  },
  emergencyCorridor: {
    label: "Noise corridor",
    description:
      "Main roads near fire stations, hospitals and police stations: where sirens and through-traffic noise are most likely.",
    group: "neighborhood",
  },
  recreation: {
    label: "Recreation",
    description: "Parks and trails.",
    group: "neighborhood",
  },
};

/**
 * Keys that older API rows and shared links still use, mapped to the pill that
 * replaced them. Several old keys can fold into one new pill.
 */
export const LEGACY_FACTOR_ALIASES: Readonly<Record<string, FactorKey>> = {
  premiumRetail: "shopping",
  trailPopularity: "recreation",
  road: "traffic",
  gasStation: "gasConvenience",
  convenienceStore: "gasConvenience",
};

const CURRENT_KEYS: ReadonlySet<string> = new Set(FACTOR_KEY_LIST);

/** The current key for a current or legacy factor key, else null. */
export function canonicalFactorKey(value: unknown): FactorKey | null {
  if (typeof value !== "string") return null;
  if (CURRENT_KEYS.has(value)) return value as FactorKey;
  return Object.hasOwn(LEGACY_FACTOR_ALIASES, value)
    ? LEGACY_FACTOR_ALIASES[value]
    : null;
}

/** Every factor, in display order. */
export const FACTOR_KEYS = Object.keys(FACTORS) as FactorKey[];

/** Alias kept for callers that mean "everything the API scores"; identical to `FACTOR_KEYS`. */
export const ALL_FACTOR_KEYS = FACTOR_KEYS;
