import type { FactorKey } from "@/lib/api/types";
import { FACTOR_KEYS } from "@/lib/score/factors";

export interface FactorGuideEntry {
  /** One short sentence for the home page grid. */
  blurb: string;
  /** What the sub-score is built from. Distances are in feet and miles. */
  measures: string;
  /** Whether a high sub-score means more of the thing, or less of it. */
  direction: "closer" | "fewer" | "lower";
  /** Short statement of what counts as good. */
  better: string;
  /** Why that direction is treated as good. */
  why: string;
  /** Default relative weight in the overall score (docs/SCORING.md section 2). */
  weight: number;
  /** An honest limit of the data or method. */
  caveat: string;
}

/**
 * Plain-language guide to the thirteen factors. Weights are the relative
 * defaults from docs/SCORING.md (only their ratios matter); the distances
 * mirror the scoring curves, shown in feet and miles.
 */
export const FACTOR_GUIDE: Record<FactorKey, FactorGuideEntry> = {
  grocery: {
    blurb: "How close the nearest supermarkets are.",
    measures:
      "Supermarkets and grocery shops from OpenStreetMap: the distance to the nearest one, and how many are within about 0.3 mi (1,600 ft).",
    direction: "closer",
    better: "Closer, and more of them, is better.",
    why: "Being able to get food on foot is the clearest everyday convenience, and grocers tend to cluster where other amenities are.",
    weight: 14,
    caveat:
      "Store size and price are not measured.",
  },
  restaurant: {
    blurb: "Places to eat within a short walk.",
    measures:
      "Restaurants from OpenStreetMap: the distance to the nearest one, and how many are within about 0.3 mi (1,600 ft).",
    direction: "closer",
    better: "Closer, and more of them, is better.",
    why: "Places to eat on foot make a neighborhood easy to live in and tend to mark a lively area.",
    weight: 10,
    caveat:
      "Counts places tagged as restaurants, not quality, price or cuisine.",
  },
  cafe: {
    blurb: "Coffee shops that mark a lively street.",
    measures:
      "Cafes and coffee shops from OpenStreetMap: the distance to the nearest, and the count within about 0.3 mi.",
    direction: "closer",
    better: "Closer, and more of them, is better.",
    why: "Cafes are a good sign of an active, walkable street.",
    weight: 8,
    caveat:
      "Opening hours and quality are not measured, and OpenStreetMap coverage varies between neighborhoods.",
  },
  bar: {
    blurb: "Bars nearby, for nightlife.",
    measures:
      "Bars, pubs and beer gardens from OpenStreetMap: the distance to the nearest one, and how many are within about 0.3 mi (1,600 ft).",
    direction: "closer",
    better: "Closer, and more of them, is better.",
    why: "Nightlife within walking distance appeals to many people, so it counts, but at a lower weight than restaurants.",
    weight: 5,
    caveat:
      "Some people want quiet instead. Lower the importance of this factor if that is you.",
  },
  gym: {
    blurb: "Fitness centres within easy reach.",
    measures:
      "Fitness centres from OpenStreetMap: the distance to the nearest, and the count within about 0.3 mi.",
    direction: "closer",
    better: "Closer, and more of them, is better.",
    why: "A gym nearby makes a regular workout easy to keep up.",
    weight: 9,
    caveat:
      "Membership cost and quality are unknown; a boutique studio counts the same as a large gym.",
  },
  shopping: {
    blurb: "Department stores and everyday retail nearby.",
    measures:
      "Distance to the nearest Whole Foods, Starbucks and Target, combined into one signal of retail nearby.",
    direction: "closer",
    better: "Closer to these stores is better.",
    why: "These chains tend to open where demand and foot traffic are strong, so they are a rough sign of a sought-after area.",
    weight: 4,
    caveat:
      "A brand-based proxy, not a measure of quality of life. Rural and some urban areas simply lack these stores.",
  },
  recreation: {
    blurb: "Parks and trails nearby.",
    measures:
      "Parks and running trails from OpenStreetMap (paths, footways, tracks and running tracks): the distance to the nearest, and the count within 0.5 mi.",
    direction: "closer",
    better: "Closer to more parks and trails is better.",
    why: "Green space nearby suggests a place people like to be outside, and gives you somewhere to run or walk.",
    weight: 5,
    caveat:
      "Based on mapped parks and trails, so it shows that one exists, not how many people use it.",
  },
  gasConvenience: {
    blurb: "Fuel and quick-stop stores nearby.",
    measures:
      "Gas stations and convenience stores from OpenStreetMap: the distance to the nearest, and the count within about 0.3 mi.",
    direction: "closer",
    better: "Closer fuel and quick-stop stores are better.",
    why: "A fill-up or a late-night essential should be a short trip away. This counts in your favor, not against a place.",
    weight: 6,
    caveat:
      "Where a dense cluster of stores means a busy corner, that shows up in the noise corridor and traffic factors instead.",
  },
  transit: {
    blurb: "Subway, rail and bus stops close by.",
    measures:
      "Transit stops from the MTA, LIRR, Metro-North, NJ Transit and PATH schedule feeds, plus OpenStreetMap stops: the distance to the nearest stop, and the number of stops within 0.5 mi (about 2,600 ft).",
    direction: "closer",
    better: "Closer, and more stops, is better.",
    why: "Frequent, nearby transit lets you get around without a car.",
    weight: 14,
    caveat:
      "Counts stops, not how often trains and buses run or where they go, and a stop at the edge of the 0.5 mi circle counts like one at your door.",
  },
  airport: {
    blurb: "Estimated drive to JFK, LGA or Newark.",
    measures:
      "Estimated drive time to the nearest of JFK, LaGuardia and Newark Liberty.",
    direction: "lower",
    better: "A shorter drive is better.",
    why: "Quick airport access matters for frequent flyers and for visitors.",
    weight: 5,
    caveat:
      "Drive time is currently estimated from straight-line distance, which understates real driving time. Treat it as a sense of which places are nearer, not as minutes.",
  },
  traffic: {
    blurb: "Fewer busy roads nearby.",
    measures:
      "A congestion estimate built from the road network in OpenStreetMap: the type of each nearby road (highways count the most), weighted by how close it is, with a bonus for single-lane stretches of through roads.",
    direction: "lower",
    better: "Fewer and quieter busy roads nearby is better.",
    why: "Heavy through traffic means noise, slower trips and harder crossings.",
    weight: 4,
    caveat:
      "A hand-tuned estimate from the type of road, not real traffic counts or live traffic.",
  },
  school: {
    blurb: "Nearby schools and district test ratings.",
    measures:
      "Public school locations (NCES) and district ratings (state test proficiency, as a percentile within each state): the distance to the nearest school and how many are within 1 mi make up 20% of the sub-score (proximity), and the district rating makes up the other 80%.",
    direction: "closer",
    better: "More schools nearby, closer, and in a higher-rated district, is better.",
    why: "Schools nearby matter to families and tend to hold value. The rating carries most of the weight because a school next door that rates poorly is not what most families are looking for.",
    weight: 10,
    caveat:
      "Where no rating exists the sub-score is left out (null, never zero) rather than guessed, and we show the proximity on its own with a note that the rating is unavailable. A district rating is a rough stand-in for any one school's quality.",
  },
  emergencyCorridor: {
    blurb: "Distance from siren-heavy main roads.",
    measures:
      "Distance to real fire stations, hospitals and police stations. Main roads (primary roads, trunk roads and highways) near those facilities count as noise corridors, because that is where sirens travel. The penalty is halved when your street is a side street rather than facing the corridor.",
    direction: "lower",
    better: "Farther from main roads near emergency facilities is better.",
    why: "Sirens are a common source of noise, and the main roads next to fire stations, hospitals and police stations are where they run.",
    weight: 12,
    caveat:
      "A rough proxy for siren noise, not actual dispatch data. Where facility locations are missing it falls back to the major-road estimate.",
  },
};

/** The thirteen factors, in display order. */
export const FACTOR_GUIDE_ORDER: readonly FactorKey[] = FACTOR_KEYS;

/** The largest default weight, used to scale the weight bars. */
export const MAX_FACTOR_WEIGHT = Math.max(
  ...Object.values(FACTOR_GUIDE).map((entry) => entry.weight),
);
