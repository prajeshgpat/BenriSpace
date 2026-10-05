"use client";

import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

import {
  COMPARE_ROWS,
  MAX_COMPARE,
  bestInRow,
  biggestDifferences,
  gapFromBest,
  rowValue,
  type CompareRow,
  type ComparePlace,
} from "@/lib/compare";
import { FACTORS } from "@/lib/score/factors";
import { scorePillColor } from "@/lib/score/pillColors";

import styles from "./CompareDrawer.module.css";

const RADIUS = 52;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

function MiniRing({ value }: { value: number }) {
  return (
    <svg className={styles.ring} viewBox="0 0 120 120" aria-hidden="true" focusable="false">
      <circle className={styles.track} cx="60" cy="60" r={RADIUS} />
      {value > 0 ? (
        <circle
          className={styles.fill}
          cx="60"
          cy="60"
          r={RADIUS}
          stroke={scorePillColor(value)}
          strokeDasharray={CIRCUMFERENCE}
          strokeDashoffset={CIRCUMFERENCE * (1 - value / 100)}
        />
      ) : null}
    </svg>
  );
}

function rowLabel(row: CompareRow): string {
  return row === "overall" ? "Overall score" : FACTORS[row].label;
}

interface CompareDrawerProps {
  places: readonly ComparePlace[];
  onRemove: (id: string) => void;
  onClear: () => void;
}

/** A bar that opens a side-by-side table of the pinned places. */
export function CompareDrawer({ places, onRemove, onClear }: CompareDrawerProps) {
  const [open, setOpen] = useState(false);
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);

  // Nothing left to show: close, so the next pin does not pop the dialog open.
  useEffect(() => {
    if (places.length === 0) setOpen(false);
  }, [places.length]);

  useEffect(() => {
    if (!open) return;
    dialogRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  if (places.length === 0) return null;

  const differences = biggestDifferences(places);
  const labelById = new Map(places.map((p) => [p.id, p.label]));
  const nameOf = (ids: readonly string[]) =>
    ids.map((id) => labelById.get(id) ?? id).join(" and ");

  // Portalled out of the panel: a bottom sheet's transform would otherwise
  // become the containing block for these fixed elements.
  return createPortal(
    <>
      <div className={styles.bar}>
        <button type="button" className={styles.open} onClick={() => setOpen(true)}>
          Compare places ({places.length})
        </button>
      </div>
      {open ? (
        <div className={styles.scrim}>
          <div
            ref={dialogRef}
            className={styles.dialog}
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            tabIndex={-1}
          >
            <div className={styles.head}>
              <h2 id={titleId} className={styles.title}>
                Compare places
              </h2>
              <div className={styles.actions}>
                <button type="button" className={styles.text} onClick={onClear}>
                  Clear all
                </button>
                <button type="button" className={styles.text} onClick={() => setOpen(false)}>
                  Close
                </button>
              </div>
            </div>
            {places.length < 2 ? (
              <p className={styles.empty}>
                Pin at least one more place (up to {MAX_COMPARE}) to see which is best on each row.
              </p>
            ) : null}
            {differences.length > 0 ? (
              <section className={styles.differences} aria-label="Biggest differences">
                <h3 className={styles.diffTitle}>Biggest differences</h3>
                <ul className={styles.diffList}>
                  {differences.map((d) => (
                    <li key={d.row}>
                      <strong>{FACTORS[d.row].label}</strong>: {nameOf(d.leaderIds)} leads by{" "}
                      {d.spread} {d.spread === 1 ? "point" : "points"} over {nameOf(d.trailerIds)}
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
            <div className={styles.scroll}>
              <table className={styles.table}>
                <caption className="sr-only">
                  Scores for each pinned place. The best score in each row is marked.
                </caption>
                <thead>
                  <tr>
                    <td />
                    {places.map((place) => (
                      <th key={place.id} scope="col">
                        <div className={styles.place}>
                          <span className={styles.name}>{place.label}</span>
                          {place.neighborhood && place.neighborhood !== place.label ? (
                            <span className={styles.sub}>{place.neighborhood}</span>
                          ) : null}
                          <button
                            type="button"
                            className={styles.text}
                            aria-label={`Remove ${place.label} from compare`}
                            onClick={() => onRemove(place.id)}
                          >
                            Remove
                          </button>
                        </div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {COMPARE_ROWS.map((row) => {
                    const best = bestInRow(places, row);
                    return (
                      <tr key={row}>
                        <th scope="row">{rowLabel(row)}</th>
                        {places.map((place) => {
                          const value = rowValue(place, row);
                          const gap = gapFromBest(places, place, row);
                          return (
                            <td key={place.id}>
                              {value === null ? (
                                <span className={styles.empty}>No data</span>
                              ) : (
                                <span className={styles.cell} data-best={best.has(place.id)}>
                                  <MiniRing value={value} />
                                  <span>{value}</span>
                                  {gap ? (
                                    <span className={styles.gap}>
                                      <span aria-hidden="true">{`−${gap}`}</span>
                                      <span className="sr-only">{`${gap} behind the best`}</span>
                                    </span>
                                  ) : null}
                                  {best.has(place.id) ? <span className="sr-only"> (best)</span> : null}
                                </span>
                              )}
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      ) : null}
    </>,
    document.body,
  );
}
