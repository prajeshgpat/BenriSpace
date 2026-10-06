import type { FactorKey } from "@/lib/api/types";
import { FACTOR_KEYS } from "@/lib/score/factors";

/** How each factor reads in "good for X and Y". */
const NOUN: Record<FactorKey, string> = {
  grocery: "groceries",
  restaurant: "restaurants",
  cafe: "cafes",
  bar: "bars",
  gym: "gyms",
  shopping: "shopping",
  transit: "transit",
  airport: "airport access",
  gasConvenience: "gas and convenience stores",
  traffic: "low traffic",
  school: "schools",
  emergencyCorridor: "quiet streets",
  recreation: "parks and trails",
};

/** One question per factor: about the selected place, and across the metro. */
const PER_FACTOR: Record<FactorKey, { here: string; metro: string }> = {
  grocery: { here: "Is there a good grocery store close by?", metro: "Where are the best areas for groceries?" },
  restaurant: { here: "How many restaurants are within walking distance?", metro: "Which areas have the most restaurants?" },
  cafe: { here: "Is there a good cafe within walking distance?", metro: "Which areas have the best cafes?" },
  bar: { here: "Are there bars within walking distance?", metro: "Which areas have the best bars?" },
  gym: { here: "Is there a gym close by?", metro: "Which areas have the most gyms?" },
  shopping: { here: "Is there good shopping nearby?", metro: "Which areas have the best shopping?" },
  transit: { here: "How good is the transit near here?", metro: "Which areas have the best transit?" },
  airport: { here: "How long is the trip to the airport?", metro: "Which areas are closest to an airport?" },
  gasConvenience: { here: "Is there a gas station or convenience store close by?", metro: "Which areas are best for quick errands?" },
  traffic: { here: "Is the traffic around here light?", metro: "Which areas have the least traffic?" },
  school: { here: "How are the schools near here?", metro: "Which areas have the best schools?" },
  emergencyCorridor: { here: "Is it quiet here, away from sirens?", metro: "Which areas are the quietest?" },
  recreation: { here: "Are there parks close by?", metro: "Which areas have the best parks and trails?" },
};

const MULTI_STOP = "Find a neighborhood near my work, a Trader Joe's and a Planet Fitness";

/**
 * Exactly three suggested questions that follow the selected factors
 * (`undefined` means all thirteen are on): the first two factors combined, the
 * third on its own, then the multi-stop search.
 */
export function starterQuestions(
  factors: readonly FactorKey[] | undefined,
  hasPlace: boolean,
): string[] {
  const picked = factors ? FACTOR_KEYS.filter((key) => factors.includes(key)) : FACTOR_KEYS;
  const single = (key: FactorKey) => PER_FACTOR[key][hasPlace ? "here" : "metro"];
  const pair = (a: FactorKey, b: FactorKey) =>
    hasPlace
      ? `Is it good for ${NOUN[a]} and ${NOUN[b]}?`
      : `Which neighborhoods are best for ${NOUN[a]} and ${NOUN[b]}?`;
  const overview = hasPlace
    ? "What are the best things about this area?"
    : "Which neighborhoods score best overall?";
  const quiet = hasPlace ? "Find a quieter area near here" : "Which neighborhoods are the quietest?";

  const first =
    picked.length >= 2 ? pair(picked[0], picked[1]) : picked.length === 1 ? single(picked[0]) : overview;
  const second =
    picked.length >= 3 ? single(picked[2]) : picked.length === 2 ? single(picked[1]) : quiet;
  // One factor leaves nothing else to say about it; fall back to the generic quiet question.
  return [first, picked.length === 1 ? quiet : second, MULTI_STOP];
}
