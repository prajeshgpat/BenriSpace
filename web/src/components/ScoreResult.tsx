import type { ExplanationState } from "@/hooks/useScoreLookup";
import type { Score } from "@/lib/api/types";
import {
  SCORE_MAX,
  bandLabel,
  buildFactorSections,
  describeScoredLocation,
  formatComputedAt,
  roundScore,
  summarizeCoverage,
  type FactorRow,
} from "@/lib/score/presentation";

import { CopyLinkButton } from "./CopyLinkButton";
import styles from "./ScoreResult.module.css";

interface ScoreResultProps {
  address: string;
  score: Score;
  explanation: ExplanationState;
}

export function ScoreResult({ address, score, explanation }: ScoreResultProps) {
  const sections = buildFactorSections(score.subScores);
  const coverage = summarizeCoverage(score.subScores);
  const computedOn = formatComputedAt(score.computedAt);

  return (
    <article className={styles.card} aria-labelledby="result-heading">
      <header className={styles.header}>
        <p className={styles.eyebrow}>Convenience score</p>
        <h2 id="result-heading" className={styles.address}>
          {address}
        </h2>
        <p className={styles.location}>{describeScoredLocation(score)}</p>
      </header>

      <div className={styles.summary}>
        <ScoreRing value={score.compositeScore} />
        <div className={styles.summaryText}>
          <p className={styles.band}>{bandLabel(score.compositeScore)}</p>
          <p className={styles.coverage}>{coverage.summary}</p>
        </div>
      </div>

      <section className={styles.section} aria-labelledby="explanation-heading">
        <h3 id="explanation-heading" className={styles.sectionHeading}>
          Why this score
        </h3>
        <ExplanationText explanation={explanation} />
      </section>

      <section className={styles.section} aria-labelledby="factors-heading">
        <h3 id="factors-heading" className={styles.sectionHeading}>
          Factor breakdown
        </h3>
        <p className={styles.note}>
          Each factor is scored from 0 to {SCORE_MAX} relative to the rest of
          the metro area. Higher is always better.
        </p>
        {sections.map((section) => (
          <div key={section.group} className={styles.group}>
            <h4 className={styles.groupHeading}>{section.title}</h4>
            <ul className={styles.factors}>
              {section.rows.map((row) => (
                <FactorItem key={row.key} row={row} />
              ))}
            </ul>
          </div>
        ))}
      </section>

      <footer className={styles.footer}>
        <p className={styles.meta}>
          <span>Weights {score.weightsVersion}</span>
          {computedOn ? (
            <span>
              Computed <time dateTime={score.computedAt}>{computedOn}</time>
            </span>
          ) : null}
        </p>
        <CopyLinkButton />
      </footer>
    </article>
  );
}

const RING_RADIUS = 52;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;

function ScoreRing({ value }: { value: number }) {
  const rounded = roundScore(value);
  const offset = RING_CIRCUMFERENCE * (1 - rounded / SCORE_MAX);

  return (
    <div className={styles.ring}>
      <svg viewBox="0 0 120 120" aria-hidden="true" focusable="false">
        <circle className={styles.ringTrack} cx="60" cy="60" r={RING_RADIUS} />
        {rounded > 0 ? (
          <circle
            className={styles.ringFill}
            cx="60"
            cy="60"
            r={RING_RADIUS}
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

function ExplanationText({ explanation }: { explanation: ExplanationState }) {
  switch (explanation.status) {
    case "loading":
      return (
        <p className={styles.explanationPending} aria-busy="true">
          Writing the explanation…
        </p>
      );
    case "ready":
      return <p className={styles.explanation}>{explanation.text}</p>;
    case "unavailable":
      return (
        <p className={styles.explanationPending}>
          An explanation isn&rsquo;t available for this score right now. The
          breakdown below still shows how each factor contributed.
        </p>
      );
  }
}

function FactorItem({ row }: { row: FactorRow }) {
  const hasData = row.value !== null;

  return (
    <li className={styles.factor} data-factor={row.key}>
      <div className={styles.factorHead}>
        <span className={styles.factorLabel}>{row.label}</span>
        {hasData ? (
          <span className={styles.factorValue}>
            <span className={styles.factorBand}>{row.band}</span>
            <span className={styles.factorNumber}>{row.display}</span>
            <span className="sr-only"> out of {SCORE_MAX}</span>
          </span>
        ) : (
          <span className={styles.factorMissing}>{row.display}</span>
        )}
      </div>
      <div
        className={hasData ? styles.track : styles.trackEmpty}
        aria-hidden="true"
      >
        {hasData && row.value !== 0 ? (
          <div className={styles.fill} style={{ width: `${row.value}%` }} />
        ) : null}
      </div>
      <p className={styles.factorDescription}>{row.description}</p>
    </li>
  );
}
