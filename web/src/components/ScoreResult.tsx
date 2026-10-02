import type { ExplanationState } from "@/hooks/useScoreLookup";
import type { AreaInfo, Score, SchoolInfo } from "@/lib/api/types";
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

import {
  GREATSCHOOLS_DISTRICTS_URL,
  GREATSCHOOLS_LINK_LABEL,
} from "@/lib/schoolLinks";

import { formatArea } from "@/lib/units";

import { CopyLinkButton } from "./CopyLinkButton";
import styles from "./ScoreResult.module.css";

interface ScoreResultProps {
  address: string;
  /** A street address looked up for a clicked point, shown instead of coordinates. */
  readableAddress?: string | null;
  score: Score;
  /** Present when the score is for a secondary-road area rather than a grid square. */
  area?: AreaInfo | null;
  explanation: ExplanationState;
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

/** Cell footprint in miles, shown so the average is not mistaken for a point score. */
export function areaNote(cellCount: number): string {
  return cellCount === 1
    ? "Scores blend 1 grid square (about 0.6 × 0.4 mi), so this area's score is an average."
    : `Scores blend ${cellCount} grid squares (about 0.6 × 0.4 mi each), so this area's score is an average.`;
}

export function ScoreResult({
  address,
  readableAddress = null,
  score,
  area = null,
  explanation,
}: ScoreResultProps) {
  const sections = buildFactorSections(score.subScores);
  const coverage = summarizeCoverage(score.subScores);
  const computedOn = formatComputedAt(score.computedAt);
  const boundedLabel = area ? areaLabel(area.boundedBy) : null;

  return (
    <article
      className={styles.card}
      aria-labelledby="result-heading"
      aria-describedby={boundedLabel ? "area-label" : undefined}
    >
      <header className={styles.header}>
        <p className={styles.eyebrow}>Convenience score</p>
        <h2 id="result-heading" className={styles.address}>
          {address}
        </h2>
        {area ? (
          <>
            <p id="area-label" className={styles.location}>
              {boundedLabel ?? describeScoredLocation(score, readableAddress)}
            </p>
            <p className={styles.note} data-testid="area-note">
              About {formatArea(area.areaSqMi)}. {areaNote(area.cellCount)}
            </p>
          </>
        ) : (
          <p className={styles.location}>
            {describeScoredLocation(score, readableAddress)}
          </p>
        )}
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

      <details className={styles.breakdown}>
        <summary className={styles.breakdownSummary}>
          <h3 id="factors-heading" className={styles.sectionHeading}>
            Factor breakdown
          </h3>
          <svg
            className={styles.chevron}
            viewBox="0 0 24 24"
            aria-hidden="true"
            focusable="false"
          >
            <path d="M6 14l6-6 6 6" />
          </svg>
        </summary>
        <p className={styles.note}>
          Each factor is scored from 0 to {SCORE_MAX} relative to the rest of
          the metro area. Higher is always better.
        </p>
        {sections.map((section) => (
          <div key={section.group} className={styles.group}>
            <h4 className={styles.groupHeading}>{section.title}</h4>
            <ul className={styles.factors}>
              {section.rows.map((row) => (
                <FactorItem
                  key={row.key}
                  row={row}
                  school={row.key === "school" ? score.school : null}
                />
              ))}
            </ul>
          </div>
        ))}
        <p className={styles.note} data-testid="underlying-note">
          {UNDERLYING_NOTE}
        </p>
      </details>

      <footer className={styles.footer}>
        <p className={styles.meta}>
          <span>Weights {score.weightsVersion}</span>
          {computedOn ? (
            <span>
              Computed <time dateTime={score.computedAt}>{computedOn}</time>
            </span>
          ) : null}
        </p>
        <div className={styles.actions}>
          <CopyLinkButton />
        </div>
      </footer>
    </article>
  );
}

export const UNDERLYING_NOTE =
  "Also counted in the overall score: premium retail and running route popularity (Whole Foods, Starbucks, Target and nearby running routes).";

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

function FactorItem({
  row,
  school,
}: {
  row: FactorRow;
  school?: SchoolInfo | null;
}) {
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
      {school ? <SchoolDetail school={school} /> : null}
    </li>
  );
}
