import { useId, memo } from "react";

import type { FactorKey } from "@/lib/api/types";
import {
  FACTOR_GROUPS,
  FACTOR_KEYS,
  FACTORS,
  type FactorGroup,
} from "@/lib/score/factors";
import {
  IMPORTANCE_LEVELS,
  importanceOf,
  setImportance,
  toggleFactor,
  type FactorSelection,
  type Importance,
} from "@/lib/map/selection";

import { FactorIcon } from "@/lib/factorIcons";
import { scorePillColor } from "@/lib/score/pillColors";
import { SCORE_MAX, roundScore } from "@/lib/score/presentation";

import styles from "./FactorControls.module.css";

const IMPORTANCE_LABELS: Record<Importance, string> = {
  low: "Low",
  normal: "Normal",
  high: "High",
};

const GROUPS = Object.keys(FACTOR_GROUPS) as FactorGroup[];

/** Per-factor 0-100 scores for the place on screen; `null` means no data there. */
export type FactorScores = Partial<Record<FactorKey, number | null>>;

interface FactorControlsProps {
  selection: FactorSelection;
  onChange: (selection: FactorSelection) => void;
  /** When set, each selected factor shows its score on its toggle. */
  scores?: FactorScores | null;
}

const RING_RADIUS = 14;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;

/** Decorative score ring; the number is also in the toggle's accessible name. */
function ScoreBadge({ value }: { value: number | null }) {
  const rounded = value === null ? null : roundScore(value);
  return (
    <span
      className={styles.badge}
      data-testid="factor-ring"
      data-state={rounded === null ? "none" : "scored"}
      aria-hidden="true"
    >
      <svg viewBox="0 0 32 32" focusable="false">
        <circle className={styles.badgeTrack} cx="16" cy="16" r={RING_RADIUS} />
        {rounded !== null && rounded > 0 ? (
          <circle
            className={styles.badgeFill}
            cx="16"
            cy="16"
            r={RING_RADIUS}
            stroke={scorePillColor(rounded)}
            strokeDasharray={RING_CIRCUMFERENCE}
            strokeDashoffset={RING_CIRCUMFERENCE * (1 - rounded / SCORE_MAX)}
          />
        ) : null}
      </svg>
      <span className={styles.badgeValue}>{rounded ?? "n/a"}</span>
    </span>
  );
}

function FactorControlsImpl({
  selection,
  onChange,
  scores = null,
}: FactorControlsProps) {
  const headingId = useId();
  return (
    <section className={styles.section} aria-labelledby={headingId}>
      <h2 id={headingId} className={styles.heading}>
        Factors
      </h2>

      <div className={styles.body}>
        {GROUPS.map((group) => (
          <fieldset key={group} className={styles.fieldset}>
            <legend className={styles.legend}>{FACTOR_GROUPS[group]}</legend>
            <div className={styles.chips}>
              {FACTOR_KEYS.filter((key) => FACTORS[key].group === group).map(
                (key) => {
                  const on = selection.factors.includes(key);
                  const shown = scores !== null && on;
                  const value = scores?.[key] ?? null;
                  return (
                    <label
                      key={key}
                      className={styles.toggle}
                      title={FACTORS[key].description}
                    >
                      <input
                        type="checkbox"
                        checked={on}
                        onChange={() => onChange(toggleFactor(selection, key))}
                      />
                      <FactorIcon factor={key} className={styles.icon} />
                      <span className={styles.name}>{FACTORS[key].label}</span>
                      {shown ? (
                        <>
                          <span className="sr-only">
                            {value === null
                              ? ", on, no data for this place"
                              : `, on, scored ${roundScore(value)} out of ${SCORE_MAX}`}
                          </span>
                          <ScoreBadge value={value} />
                        </>
                      ) : null}
                    </label>
                  );
                },
              )}
            </div>
          </fieldset>
        ))}

        <details className={styles.importance}>
          <summary>
            Adjust importance
            {Object.keys(selection.importance).length > 0 ? (
              <span className={styles.adjusted}> · customised</span>
            ) : null}
          </summary>
          {selection.factors.length === 0 ? (
            <p className={styles.empty}>
              Turn on a factor to set how much it counts.
            </p>
          ) : (
            <div className={styles.importanceList}>
              {selection.factors.map((key) => (
                <ImportanceRow
                  key={key}
                  factor={key}
                  selection={selection}
                  onChange={onChange}
                />
              ))}
            </div>
          )}
        </details>

        <p className={styles.note}>
          <strong>Why isn&rsquo;t anywhere 100?</strong> Scores are relative
          within each metro area, so no spot is the best on every factor at
          once. Pick one or two factors to see where each is at its maximum.
        </p>
      </div>
    </section>
  );
}

interface ImportanceRowProps {
  factor: FactorKey;
  selection: FactorSelection;
  onChange: (selection: FactorSelection) => void;
}

function ImportanceRow({ factor, selection, onChange }: ImportanceRowProps) {
  const selectId = useId();
  const { label } = FACTORS[factor];

  return (
    <div className={styles.importanceRow}>
      <label htmlFor={selectId} className={styles.importanceLabel}>
        <FactorIcon factor={factor} className={styles.icon} />
        <span>{label}</span>
      </label>
      <select
        id={selectId}
        className={styles.select}
        value={importanceOf(selection, factor)}
        onChange={(event) =>
          onChange(
            setImportance(selection, factor, event.target.value as Importance),
          )
        }
      >
        {IMPORTANCE_LEVELS.map((level) => (
          <option key={level} value={level}>
            {IMPORTANCE_LABELS[level]}
          </option>
        ))}
      </select>
    </div>
  );
}

/** Skips re-rendering while the map pans and nothing it shows has changed. */
export const FactorControls = memo(FactorControlsImpl);
