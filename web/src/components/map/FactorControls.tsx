import { useId } from "react";

import type { FactorKey } from "@/lib/api/types";
import {
  FACTOR_GROUPS,
  FACTOR_KEYS,
  FACTORS,
  type FactorGroup,
} from "@/lib/score/factors";
import {
  ALL_FACTORS,
  IMPORTANCE_LEVELS,
  PRESETS,
  activePresetId,
  applyPreset,
  createSelection,
  importanceOf,
  setImportance,
  toggleFactor,
  type FactorSelection,
  type Importance,
} from "@/lib/map/selection";

import { FactorIcon } from "@/lib/factorIcons";

import styles from "./FactorControls.module.css";

const IMPORTANCE_LABELS: Record<Importance, string> = {
  low: "Low",
  normal: "Normal",
  high: "High",
};

const GROUPS = Object.keys(FACTOR_GROUPS) as FactorGroup[];

interface FactorControlsProps {
  selection: FactorSelection;
  onChange: (selection: FactorSelection) => void;
}

export function FactorControls({ selection, onChange }: FactorControlsProps) {
  const preset = activePresetId(selection);
  const allOn = selection.factors.length === FACTOR_KEYS.length;
  const noneOn = selection.factors.length === 0;

  return (
    <details className={styles.section} open>
      <summary className={styles.summary}>
        <h2 className={styles.heading}>Factors</h2>
        <span className={styles.count}>
          {selection.factors.length} of {FACTOR_KEYS.length} on
        </span>
        <svg
          className={styles.chevron}
          viewBox="0 0 24 24"
          aria-hidden="true"
          focusable="false"
        >
          <path d="M6 14l6-6 6 6" />
        </svg>
      </summary>

      <div className={styles.body}>
        <div className={styles.group} role="group" aria-label="Presets">
          {PRESETS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={styles.chip}
              aria-pressed={preset === item.id}
              title={item.description}
              onClick={() => onChange(applyPreset(item))}
            >
              {item.label}
            </button>
          ))}
        </div>

        <div className={styles.bulk}>
          <button
            type="button"
            className={styles.linkButton}
            disabled={allOn && Object.keys(selection.importance).length === 0}
            onClick={() => onChange(ALL_FACTORS)}
          >
            Select all
          </button>
          <button
            type="button"
            className={styles.linkButton}
            disabled={noneOn}
            onClick={() => onChange(createSelection([]))}
          >
            Select none
          </button>
        </div>

        {GROUPS.map((group) => (
          <fieldset key={group} className={styles.fieldset}>
            <legend className={styles.legend}>{FACTOR_GROUPS[group]}</legend>
            <div className={styles.chips}>
              {FACTOR_KEYS.filter((key) => FACTORS[key].group === group).map(
                (key) => (
                  <label
                    key={key}
                    className={styles.toggle}
                    title={FACTORS[key].description}
                  >
                    <input
                      type="checkbox"
                      checked={selection.factors.includes(key)}
                      onChange={() => onChange(toggleFactor(selection, key))}
                    />
                    <FactorIcon factor={key} className={styles.icon} />
                    <span>{FACTORS[key].label}</span>
                  </label>
                ),
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
    </details>
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
