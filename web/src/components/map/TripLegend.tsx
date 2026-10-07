import { memo } from "react";

import { anchorName, type TripOverlay, type TripStatus } from "@/hooks/useTripPlanner";

import styles from "./TripLegend.module.css";

interface TripLegendProps {
  overlay: TripOverlay;
  status: TripStatus;
}

/**
 * What the travel-area colours on the map mean: the searched place's area (while there is no
 * overlap) or the overlap of all the places' areas.
 */
function TripLegendImpl({ overlay, status }: TripLegendProps) {
  const searchedArea = overlay.anchors.some(
    (anchor) => anchor.index === 0 && anchor.geometry,
  );
  const overlapDrawn = status === "ready";
  // The searched place's boundary is only drawn while there is no overlap.
  const showSearched = searchedArea && !overlapDrawn;
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
            {anchorName(0)}
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
