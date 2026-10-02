import { RAMP_GRADIENT } from "@/lib/map/colors";
import type { ScoreRange } from "@/lib/map/features";
import { roundScore } from "@/lib/score/presentation";

import styles from "./MapLegend.module.css";

export function MapLegend({ range }: { range: ScoreRange | null }) {
  return (
    <div className={styles.legend} role="group" aria-label="Score legend">
      <p className={styles.title}>Score</p>
      <div className={styles.bar} style={{ background: RAMP_GRADIENT }}>
        {range ? (
          <>
            <span className={styles.tick} style={{ left: `${range.min}%` }} />
            <span className={styles.tick} style={{ left: `${range.max}%` }} />
          </>
        ) : null}
      </div>
      <div className={styles.scale} aria-hidden="true">
        <span>0</span>
        <span>100</span>
      </div>
      <p className={styles.range}>
        {range
          ? `In view: ${roundScore(range.min)} to ${roundScore(range.max)}`
          : "No scores to show"}
      </p>
      <p className="sr-only">
        Score for the selected factors. Darker purple is lower and yellow is
        higher.
      </p>
    </div>
  );
}
