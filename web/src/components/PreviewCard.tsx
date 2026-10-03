"use client";

import { useEffect, useRef } from "react";

import type { Preview } from "@/lib/map/preview";
import { roundScore } from "@/lib/score/presentation";

import styles from "./PreviewCard.module.css";

export interface PreviewCardProps {
  preview: Preview;
  /** Short readable name of the place that stays selected; null when none. */
  originLabel: string | null;
  onBack: () => void;
  onPromote: () => void;
  onClose: () => void;
}

const MAX_CHIPS = 3;

function signed(delta: number): string {
  const rounded = Math.round(delta);
  return `${rounded >= 0 ? "+" : "−"}${Math.abs(rounded)}`;
}

/** "350 5th Ave, New York, NY" becomes "350 5th Ave". */
export function shortAddress(label: string): string {
  const first = label.split(",")[0]?.trim();
  return first || label;
}

export function PreviewCard({
  preview,
  originLabel,
  onBack,
  onPromote,
  onClose,
}: PreviewCardProps) {
  const ref = useRef<HTMLElement>(null);
  const closeRef = useRef(onClose);
  useEffect(() => {
    closeRef.current = onClose;
  });

  // Esc closes the preview while focus is in the card or on the map.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      const target = event.target;
      if (!(target instanceof Element)) return;
      if (target.closest('[aria-label="Previewed area"], [aria-label="Map"]')) {
        closeRef.current();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  const { summary } = preview;
  const differences = summary?.differences?.slice(0, MAX_CHIPS) ?? [];
  const where = [summary?.distanceLabel, summary?.direction].filter(Boolean).join(" ");
  const back = originLabel ? `Back to ${shortAddress(originLabel)}` : "Back";

  return (
    <section ref={ref} className={styles.card} role="region" aria-label="Previewed area">
      <p className="sr-only" role="status">
        {`Previewing ${preview.label}. Your selected location has not changed.`}
      </p>
      <div className={styles.head}>
        <h2 className={styles.title}>{preview.label}</h2>
        {summary?.compositeScore !== undefined ? (
          <span
            className={styles.score}
            aria-label={`Score ${roundScore(summary.compositeScore)}`}
          >
            {roundScore(summary.compositeScore)}
          </span>
        ) : null}
        <button type="button" className={styles.close} onClick={onClose}>
          <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
          <span className="sr-only">Close preview</span>
        </button>
      </div>
      {where ? <p className={styles.meta}>{where} from the selected location</p> : null}
      {differences.length > 0 ? (
        <ul className={styles.chips} aria-label="Differences from the selected location">
          {differences.map((d) => (
            <li key={d.label} className={d.delta > 0 ? styles.better : styles.worse}>
              {signed(d.delta)} {d.label}
            </li>
          ))}
        </ul>
      ) : null}
      <div className={styles.actions}>
        <button type="button" className={styles.secondary} onClick={onBack}>
          {back}
        </button>
        <button type="button" className={styles.primary} onClick={onPromote}>
          Score this area
        </button>
      </div>
    </section>
  );
}
