import type { ExplanationState } from "@/hooks/useScoreLookup";
import type { AreaInfo, Score, SchoolInfo } from "@/lib/api/types";
import {
  SCORE_MAX,
  bandLabel,
  describeScoredLocation,
  roundScore,
} from "@/lib/score/presentation";

import {
  GREATSCHOOLS_DISTRICTS_URL,
  GREATSCHOOLS_LINK_LABEL,
} from "@/lib/schoolLinks";

import { scorePillColor } from "@/lib/score/pillColors";

import { CopyLinkButton } from "./CopyLinkButton";

import styles from "./ScoreResult.module.css";

interface ScoreHeaderProps {
  address: string;
  /** A street address looked up for a clicked point, shown instead of coordinates. */
  readableAddress?: string | null;
  score: Score;
  /** Present when the score is for a secondary-road area rather than a grid square. */
  area?: AreaInfo | null;
}

/** "Area bounded by Broadway, Canal St and Bowery"; null when no roads are named. */
export function areaLabel(boundedBy: readonly string[]): string | null {
  if (boundedBy.length === 0) return null;
  const head = boundedBy.slice(0, -1);
  const roads =
    head.length === 0
      ? boundedBy[0]
      : `${head.join(", ")} and ${boundedBy[boundedBy.length - 1]}`;
  return `Area bounded by ${roads}`;
}

/** Compact header: address, composite score and the copy-link action. */
export function ScoreHeader({
  address,
  readableAddress = null,
  score,
  area = null,
}: ScoreHeaderProps) {
  const boundedLabel = area ? areaLabel(area.boundedBy) : null;
  const subtitle = boundedLabel ?? describeScoredLocation(score, readableAddress);

  return (
    <article
      className={styles.card}
      aria-labelledby="result-heading"
      aria-describedby="result-subtitle"
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
          {address}
        </h2>
        <p id="result-subtitle" className={styles.location} title={subtitle}>
          {subtitle}
        </p>
        <div className={styles.actions}>
          <CopyLinkButton />
        </div>
      </div>
    </article>
  );
}

interface ScoreSummaryProps {
  score: Score;
  explanation: ExplanationState;
}

/** The written explanation (AI or rule-based); sits under the filters. */
export function ScoreSummary({ score, explanation }: ScoreSummaryProps) {
  return (
    <section className={styles.section} aria-labelledby="explanation-heading">
      <h3 id="explanation-heading" className={styles.sectionHeading}>
        Summary
      </h3>
      <ExplanationText explanation={explanation} />
      {score.school ? <SchoolDetail school={score.school} /> : null}
    </section>
  );
}

export const AI_DISCLAIMER =
  "Generated from this area's data only; may be imperfect";

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

function ExplanationText({ explanation }: { explanation: ExplanationState }) {
  switch (explanation.status) {
    case "loading":
      return (
        <p className={styles.explanationPending} aria-busy="true">
          Writing the explanation…
        </p>
      );
    case "ready":
      return (
        <>
          <p className={styles.explanation} aria-busy={explanation.updating || undefined}>
            {explanation.text}
          </p>
          {explanation.updating ? (
            <p className={styles.updating} role="status" data-testid="explanation-updating">
              Updating…
            </p>
          ) : null}
          {explanation.explanationSource === "ai" ? (
            <p
              className={styles.aiCaption}
              data-testid="ai-caption"
              title={AI_DISCLAIMER}
            >
              <svg
                viewBox="0 0 24 24"
                className={styles.aiIcon}
                aria-hidden="true"
                focusable="false"
              >
                <path d="M5 4h14v12H9l-4 4z" />
              </svg>
              <span>AI-written summary</span>
              <span className="sr-only">. {AI_DISCLAIMER}</span>
            </p>
          ) : null}
        </>
      );
    case "unavailable":
      return (
        <p className={styles.explanationPending}>
          An explanation isn&rsquo;t available for this score right now.
        </p>
      );
  }
}

function SchoolDetail({ school }: { school: SchoolInfo }) {
  const { proximity, ratingAvailable, districtName, source } = school;
  return (
    <div className={styles.schoolDetail} data-testid="school-detail">
      {ratingAvailable ? (
        <p className={styles.schoolSource}>
          {[districtName, source ? `Rating source: ${source}` : null]
            .filter(Boolean)
            .join(" · ")}
        </p>
      ) : (
        <p className={styles.schoolSource}>
          {proximity !== null && proximity !== undefined
            ? `Proximity ${Math.round(proximity)} · school rating unavailable here`
            : "School rating unavailable here"}
        </p>
      )}
      <a
        className={styles.schoolLink}
        href={GREATSCHOOLS_DISTRICTS_URL}
        target="_blank"
        rel="noreferrer"
      >
        {GREATSCHOOLS_LINK_LABEL}
      </a>
    </div>
  );
}
