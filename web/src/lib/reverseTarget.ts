import { formatLatLon, type ScoreTarget } from "@/lib/address";
import { UNNAMED_AREA } from "@/lib/map/presentation";

type CoordinateTarget = Extract<ScoreTarget, { kind: "coordinates" }>;

/**
 * True for a point whose label is only a stand-in for coordinates (a map
 * click or a best-areas entry). Typed addresses, picked suggestions and
 * "Your location" already say where they are.
 */
export function needsReadableAddress(
  target: ScoreTarget | null,
): target is CoordinateTarget {
  if (target?.kind !== "coordinates") return false;
  return (
    target.label === formatLatLon(target) ||
    target.label === UNNAMED_AREA ||
    // Older links and rows labelled a ranked area by its coordinates.
    /^Area near -?\d/.test(target.label ?? "")
  );
}
