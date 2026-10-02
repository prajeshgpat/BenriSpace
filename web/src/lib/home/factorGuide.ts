import type { FactorKey } from "@/lib/api/types";
import { FACTOR_KEYS, UNDERLYING_FACTOR_KEYS } from "@/lib/score/factors";

export interface FactorGuideEntry {
  /** What the sub-score is built from. Distances are in feet and miles. */
  measures: string;
  /** Whether a high sub-score means more of the thing, or less of it. */
  direction: "closer" | "fewer" | "lower";
  /** Short statement of what counts as good. */
  better: string;
  /** Why that direction is treated as good. */
  why: string;
  /** Default weight in the overall score (scoring/engine.py DEFAULT_WEIGHTS, version v2-handtuned). */
  weight: number;
  /** Underlying metric: counts toward the overall score but cannot be toggled. */
  underlying?: boolean;
  /** An honest limit of the data or method. */
  caveat: string;
}

/**
 * Plain-language guide to the twelve factors and two underlying metrics. Weights mirror
 * `DEFAULT_WEIGHTS` in scoring/engine.py; the distances mirror the radii in
 * the ingestion jobs, shown in feet and miles.
 */
export const FACTOR_GUIDE: Record<FactorKey, FactorGuideEntry> = {
  grocery: {
    measures:
      "Supermarkets and grocery shops from OpenStreetMap: the distance to the nearest one, and how many are within about 0.3 mi (1,600 ft).",
    direction: "closer",
    better: "Closer, and more of them, is better.",
    why: "Being able to get food on foot is the clearest everyday convenience, and grocers tend to cluster where other amenities are.",
    weight: 1.5,
    caveat:
      "Store size and price are not measured, and convenience stores are scored separately.",
  },
  restaurant: {
    measures:
      "Restaurants from OpenStreetMap: the distance to the nearest one, and how many are within about 0.3 mi (1,600 ft).",
    direction: "closer",
    better: "Closer, and more of them, is better.",
    why: "Places to eat on foot make a neighborhood easy to live in and tend to mark a lively area.",
    weight: 1.0,
    caveat:
      "Counts places tagged as restaurants, not quality, price or cuisine.",
  },
  bar: {
    measures:
      "Bars, pubs and beer gardens from OpenStreetMap: the distance to the nearest one, and how many are within about 0.3 mi (1,600 ft).",
    direction: "closer",
    better: "Closer, and more of them, is better.",
    why: "Nightlife within walking distance appeals to many people, so it counts, but at half the weight of restaurants.",
    weight: 0.5,
    caveat:
      "Some people want quiet instead. Lower the importance of this factor if that is you.",
  },
  premiumRetail: {
    measures:
      "Distance to the nearest Whole Foods, Starbucks and Target, combined into one bonus signal.",
    direction: "closer",
    better: "Closer to these stores is better.",
    why: "These chains tend to open where demand and foot traffic are strong, so they are a rough sign of a sought-after area.",
    weight: 0.75,
    underlying: true,
    caveat:
      "A brand-based proxy, not a measure of quality of life. Rural and some urban areas simply lack these stores.",
  },
  gym: {
    measures:
      "Fitness centres from OpenStreetMap: the distance to the nearest, and the count within about 0.3 mi.",
    direction: "closer",
    better: "Closer, and more of them, is better.",
    why: "A gym nearby makes a regular workout easy to keep up.",
    weight: 1.0,
    caveat: "Membership cost and quality are unknown; a boutique studio counts the same as a large gym.",
  },
  cafe: {
    measures:
      "Cafes and coffee shops from OpenStreetMap: the distance to the nearest, and the count within about 0.3 mi.",
    direction: "closer",
    better: "Closer, and more of them, is better.",
    why: "Cafes are a good sign of an active, walkable street.",
    weight: 1.0,
    caveat: "Opening hours and quality are not measured, and OpenStreetMap coverage varies between neighborhoods.",
  },
  gasStation: {
    measures:
      "Gas stations from OpenStreetMap: the distance to the nearest, and the count within about 0.3 mi.",
    direction: "fewer",
    better: "Farther away, and fewer of them, is better.",
    why: "Gas stations bring traffic, fumes and noise, and are a rough sign of car-oriented, less walkable streets. This one counts against a place.",
    weight: 1.0,
    caveat:
      "It is a proxy. A gas station nearby is useful if you drive, but the score treats it as a negative.",
  },
  convenienceStore: {
    measures:
      "Convenience stores (OpenStreetMap shop=convenience): the distance to the nearest, and the count within about 0.3 mi.",
    direction: "fewer",
    better: "Farther away, and fewer of them, is better.",
    why: "A dense cluster of convenience stores is used here as a rough proxy for a less desirable area. This is a judgment call and counts against a place.",
    weight: 0.75,
    caveat:
      "Many corner stores are genuinely handy, so this is the most debatable factor. Untick it on the map if you disagree.",
  },
  transit: {
    measures:
      "Transit stops from the MTA, LIRR, Metro-North and NJ Transit schedule feeds: the distance to the nearest stop, and the number of stops within 0.5 mi (about 2,600 ft).",
    direction: "closer",
    better: "Closer, and more stops, is better.",
    why: "Frequent, nearby transit lets you get around without a car.",
    weight: 1.5,
    caveat:
      "Counts stops, not how often trains and buses run or where they go, and a stop at the edge of the 0.5 mi circle counts like one at your door.",
  },
  school: {
    measures:
      "Public school locations (NCES) and district ratings (state test proficiency, as a percentile within each state): the distance to the nearest school and how many are within 1 mi make up 20% of the sub-score (proximity), and the district rating makes up the other 80%.",
    direction: "closer",
    better: "More schools nearby, closer, and in a higher-rated district, is better.",
    why: "Schools nearby matter to families and tend to hold value. The rating carries most of the weight because a school next door that rates poorly is not what most families are looking for.",
    weight: 1.5,
    caveat:
      "Where no rating exists the sub-score is left out (null, never zero) rather than guessed, and we show the proximity on its own with a note that the rating is unavailable. A district rating is a rough stand-in for any one school's quality.",
  },
  road: {
    measures:
      "A congestion estimate built from the road network in OpenStreetMap: the type of each nearby road (highways count the most), weighted by how close it is, with a bonus for single-lane stretches of through roads.",
    direction: "lower",
    better: "Fewer and quieter busy roads nearby is better.",
    why: "Heavy through traffic means noise, slower trips and harder crossings.",
    weight: 1.0,
    caveat:
      "A hand-tuned estimate from the type of road, not real traffic counts or live traffic.",
  },
  emergencyCorridor: {
    measures:
      "Distance to real fire stations, hospitals and police stations. Main roads (primary roads, trunk roads and highways) near those facilities count as noise corridors, because that is where sirens travel. The penalty is halved when your street is a side street rather than facing the corridor.",
    direction: "lower",
    better: "Farther from main roads near emergency facilities is better.",
    why: "Sirens are a common source of noise, and the main roads next to fire stations, hospitals and police stations are where they run.",
    weight: 0.75,
    caveat:
      "A rough proxy for siren noise, not actual dispatch data. Where facility locations are missing it falls back to the major-road estimate.",
  },
  airport: {
    measures:
      "Estimated drive time to the nearest of JFK, LaGuardia and Newark Liberty.",
    direction: "lower",
    better: "A shorter drive is better.",
    why: "Quick airport access matters for frequent flyers and for visitors.",
    weight: 0.75,
    caveat:
      "Drive time is currently estimated from straight-line distance, which understates real driving time. Treat it as a sense of which places are nearer, not as minutes.",
  },
  trailPopularity: {
    measures:
      "Running trails and paths from OpenStreetMap (paths, footways, tracks and running tracks): the distance to the nearest, and the count within 0.5 mi. It is based on mapped running trails and paths; no usage or popularity data is blended in yet.",
    direction: "closer",
    better: "Closer to more running routes is better.",
    why: "Running routes nearby suggest a place people like to be outside, and they give you somewhere to run or walk.",
    weight: 1.25,
    underlying: true,
    caveat:
      "Based on mapped running trails, so it shows that a route exists, not how many people use it. Named routes are not counted separately.",
  },
};

/** The twelve togglable factors, in display order. */
export const FACTOR_GUIDE_ORDER: readonly FactorKey[] = FACTOR_KEYS;

/** The underlying metrics shown in "Behind-the-scenes signals". */
export const UNDERLYING_GUIDE_ORDER: readonly FactorKey[] = UNDERLYING_FACTOR_KEYS;

/** The largest default weight, used to scale the weight bars. */
export const MAX_FACTOR_WEIGHT = Math.max(
  ...Object.values(FACTOR_GUIDE).map((entry) => entry.weight),
);
