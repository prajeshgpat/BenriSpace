import { memo } from "react";

import { anchorName, type TripOverlay } from "@/hooks/useTripPlanner";
import type { ReachMode } from "@/lib/api/types";

import styles from "./TripLegend.module.css";

const BY_MODE: Record<ReachMode, string> = {
  walk: "on foot",
  transit: "by train",
  drive: "by car",
};

interface TripLegendProps {
  /** The places' travel areas, while points of interest are entered; null otherwise. */
  overlay: TripOverlay | null;
  /** What the triangulation shows: an overlap, the news that there is none, or nothing. */
  status: "ready" | "empty" | null;
  /** The searched place's own travel boundary ("Show on map"), while it is drawn. */
  reach: { mode: ReachMode; minutes: number; estimate: boolean } | null;
}

/**
 * What the travel-area lines on the map mean: the searched place's boundary (pink) and the
 * overlap of all the places' areas.
 */
function TripLegendImpl({ overlay, status, reach }: TripLegendProps) {
  const overlapDrawn = status === "ready";
  // The triangulation draws the searched place's boundary only while there is no overlap.
  const plannerSearched =
    !overlapDrawn && (overlay?.anchors.some((a) => a.index === 0 && a.geometry) ?? false);
  const showSearched = reach !== null || plannerSearched;
  if (!showSearched && !overlapDrawn) return null;

  return (
    <div className={styles.legend} role="group" aria-label="Travel areas legend">
      <p className={styles.title}>Travel areas</p>
      <ul className={styles.list}>
        {showSearched ? (
          <li className={styles.item}>
            <svg
              className={styles.swatch}
              width="28"
              height="8"
              viewBox="0 0 28 8"
              aria-hidden="true"
              focusable="false"
            >
              <line x1="1" y1="4" x2="27" y2="4" strokeWidth="3" strokeLinecap="butt" />
            </svg>
            <span>
              {anchorName(0)}
              {reach ? (
                <span className={styles.detail}>
                  Within {reach.minutes} min {BY_MODE[reach.mode]}
                  {reach.estimate ? " (straight-line estimate)" : ""}
                </span>
              ) : null}
            </span>
          </li>
        ) : null}
        {overlapDrawn ? (
          <li className={styles.item}>
            <span className={styles.overlapSwatch} aria-hidden="true" />
            POI Overlap
          </li>
        ) : null}
      </ul>
    </div>
  );
}

/** Skips re-rendering while the map pans and nothing it shows has changed. */
export const TripLegend = memo(TripLegendImpl);
