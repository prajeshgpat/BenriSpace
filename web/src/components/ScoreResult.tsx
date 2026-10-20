import type { AreaInfo, Score } from "@/lib/api/types";
import {
  SCORE_MAX,
  bandLabel,
  roundScore,
} from "@/lib/score/presentation";

import { scorePillColor } from "@/lib/score/pillColors";

import { CompareButton } from "./CompareButton";
import { CopyLinkButton } from "./CopyLinkButton";

import styles from "./ScoreResult.module.css";

interface ScoreHeaderProps {
  address: string;
  /** A provisional score from the static file carries only these. */
  score: Pick<Score, "compositeScore" | "neighborhood"> & Partial<Pick<Score, "precision">>;
  /** Present when the score is for a secondary-road area rather than a grid square. */
  area?: AreaInfo | null;
  /** Pin this place for the compare view. */
  compare?: { pinned: boolean; full: boolean; onToggle: () => void };
  /** Leave out the copy-link action (it would copy the searched place's link). */
  hideCopyLink?: boolean;
}

/** Compact header: address, composite score and the copy-link action. */
export function ScoreHeader({
  address,
  score,
  area = null,
  compare,
  hideCopyLink = false,
}: ScoreHeaderProps) {
  const neighborhood = score.neighborhood?.trim() || null;
  // Never street boundaries or coordinates: the neighborhood, else the address.
  const title = neighborhood ?? address;

  return (
    <article
      className={styles.card}
      aria-labelledby="result-heading"
    >
      <ScoreRing
        value={score.compositeScore}
        title={area ? "Average of the cells in this area" : undefined}
      />
      <div className={styles.headerText}>
        <p className={styles.eyebrow}>
          Convenience score &middot; {bandLabel(score.compositeScore)}
        </p>
        <h2 id="result-heading" className={styles.address}>
          {title}
        </h2>
        {score.precision === "point" ? (
          <p className={styles.precisionNote}>Exact-point score</p>
        ) : null}
        <div className={styles.actions}>
          {hideCopyLink ? null : <CopyLinkButton />}
          {compare ? (
            <CompareButton
              name={title}
              pinned={compare.pinned}
              full={compare.full}
              onToggle={compare.onToggle}
            />
          ) : null}
        </div>
      </div>
    </article>
  );
}

const RING_RADIUS = 52;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;

function ScoreRing({ value, title }: { value: number; title?: string }) {
  const rounded = roundScore(value);
  const offset = RING_CIRCUMFERENCE * (1 - rounded / SCORE_MAX);

  return (
    <div className={styles.ring} title={title}>
      <svg viewBox="0 0 120 120" aria-hidden="true" focusable="false">
        <circle className={styles.ringTrack} cx="60" cy="60" r={RING_RADIUS} />
        {rounded > 0 ? (
          <circle
            className={styles.ringFill}
            cx="60"
            cy="60"
            r={RING_RADIUS}
            stroke={scorePillColor(rounded)}
            strokeDasharray={RING_CIRCUMFERENCE}
            strokeDashoffset={offset}
          />
        ) : null}
      </svg>
      <p className={styles.ringLabel}>
        <span className={styles.ringValue} data-testid="composite-score">
          {rounded}
        </span>
        <span className={styles.ringMax} aria-hidden="true">
          / {SCORE_MAX}
        </span>
        <span className="sr-only"> out of {SCORE_MAX}</span>
      </p>
    </div>
  );
}
