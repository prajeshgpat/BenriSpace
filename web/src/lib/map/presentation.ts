import type { ApiError } from "@/lib/api/errors";
import { describeError } from "@/lib/api/messages";
import type { FactorKey, MapTopResult, SubScores } from "@/lib/api/types";
import { FACTORS } from "@/lib/score/factors";
import { roundScore } from "@/lib/score/presentation";

export interface FactorHighlight {
  key: FactorKey;
  label: string;
  value: number;
}

/**
 * The best `count` of the factors the user selected. Factors with no data are
 * skipped, and ties keep the selection order so the result is stable.
 */
export function strongestFactors(
  subScores: SubScores,
  selected: readonly FactorKey[],
  count = 2,
): FactorHighlight[] {
  return selected
    .flatMap((key): FactorHighlight[] => {
      const raw = subScores[key];
      return raw === null
        ? []
        : [{ key, label: FACTORS[key].label, value: roundScore(raw) }];
    })
    .sort((a, b) => b.value - a.value)
    .slice(0, count);
}

const METRO_NAMES: Record<string, string> = { nyc: "New York" };

export function metroLabel(metroArea: string): string {
  return METRO_NAMES[metroArea] ?? (metroArea.toUpperCase() || "Metro area");
}

export const UNNAMED_AREA = "Unnamed area";

/** A best-area title: the neighborhood name, never raw coordinates. */
export function areaTitle(
  result: Pick<MapTopResult, "neighborhood">,
): string {
  const name = result.neighborhood?.trim();
  return name ? name : UNNAMED_AREA;
}

/**
 * "Area bounded by Bedford Ave, Nostrand Ave" becomes "Bedford Ave, Nostrand Ave";
 * null when the label is empty. Anything else is returned unchanged.
 */
export function boundaryFromLabel(areaLabel: string | null | undefined): string | null {
  const text = areaLabel?.trim().replace(/^area bounded by(\s+|$)/i, "").trim();
  return text ? text : null;
}

export function formatCount(n: number): string {
  return new Intl.NumberFormat("en-US").format(n);
}

interface PartStatus {
  status: "idle" | "loading" | "ready" | "error";
  count: number;
  error: ApiError | null;
}

export interface MapStatusInput {
  noFactors: boolean;
  cells: PartStatus;
  top: PartStatus;
}

/** One sentence for the polite live region; empty when nothing changed worth saying. */
export function describeMapStatus({
  noFactors,
  cells,
  top,
}: MapStatusInput): string {
  if (noFactors)
    return "No factors selected. Select at least one to see scores.";

  const parts: string[] = [];
  if (top.status === "loading") parts.push("Finding the best areas…");
  else if (top.status === "error") {
    parts.push(
      `Could not load the best areas. ${describeError(top.error?.kind ?? "server").title}.`,
    );
  } else if (top.status === "ready") {
    parts.push(
      top.count === 0
        ? "No best areas found."
        : `${top.count} best ${top.count === 1 ? "area" : "areas"} found.`,
    );
  }

  if (cells.status === "error") {
    parts.push(
      `Could not load map scores. ${describeError(cells.error?.kind ?? "server").title}.`,
    );
  } else if (cells.status === "ready" && cells.count === 0) {
    parts.push("No scored cells in view.");
  }
  return parts.join(" ");
}
