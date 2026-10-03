"use client";

import { useIsMobile } from "@/hooks/useMediaQuery";
import { useSimilar } from "@/hooks/useSimilar";
import type { ApiClient } from "@/lib/api/client";
import type { PriorityQuery, SimilarDifference } from "@/lib/api/types";
import { roundScore } from "@/lib/score/presentation";

import styles from "./SimilarCard.module.css";

export interface SimilarCardProps {
  coordinates: { lat: number; lon: number } | null;
  client: Pick<ApiClient, "getSimilar">;
  priorities?: PriorityQuery;
  onFocusPoint: (lat: number, lon: number) => void;
}

const MAX_ROWS = 5;
const MAX_CHIPS = 3;

function signed(delta: number): string {
  const rounded = Math.round(delta);
  return `${rounded >= 0 ? "+" : "−"}${Math.abs(rounded)}`;
}

function Chip({ difference }: { difference: SimilarDifference }) {
  const better = difference.delta > 0;
  return (
    <li
      className={better ? styles.chipBetter : styles.chipWorse}
      data-factor={difference.factor}
    >
      {signed(difference.delta)} {difference.label}
    </li>
  );
}

export function SimilarCard({
  coordinates,
  client,
  priorities,
  onFocusPoint,
}: SimilarCardProps) {
  const { status, data, updating } = useSimilar(coordinates, client, priorities);
  // Tall content stays a single summary row on phones until opened.
  const mobile = useIsMobile();

  if (status === "idle" || status === "unavailable") return null;

  if (status === "loading" || !data) {
    return (
      <section
        className={styles.card}
        aria-label="Similar areas"
        aria-busy="true"
        data-testid="similar-skeleton"
      >
        <span className={styles.skeleton} />
        <span className={styles.skeleton} />
      </section>
    );
  }

  const results = data.results.slice(0, MAX_ROWS);
  if (results.length === 0) return null;

  return (
    <details className={styles.card} open={!mobile} aria-busy={updating || undefined}>
      <summary className={styles.summary}>
        <h3 className={styles.title}>Similar areas</h3>
        {updating ? <span className={styles.updating}>Updating…</span> : null}
      </summary>
      <ul className={styles.list} aria-label="Areas with a similar profile">
        {results.map((area, index) => {
          const name = area.areaLabel ?? `Area to the ${area.direction}`;
          return (
            <li key={`${area.latitude},${area.longitude}`} className={styles.item}>
              <div className={styles.head}>
                <span className={styles.name}>{name}</span>
                <span
                  className={styles.score}
                  aria-label={`Score ${roundScore(area.compositeScore)}`}
                >
                  {roundScore(area.compositeScore)}
                </span>
              </div>
              <p className={styles.meta}>
                {area.distanceLabel} {area.direction} &middot;{" "}
                {Math.round(area.similarity)}% similar
              </p>
              {area.differences.length > 0 ? (
                <ul className={styles.chips} aria-label="Differences from here">
                  {area.differences.slice(0, MAX_CHIPS).map((difference) => (
                    <Chip key={difference.factor} difference={difference} />
                  ))}
                </ul>
              ) : null}
              <button
                type="button"
                className={styles.action}
                aria-label={`Show similar area ${index + 1} on map`}
                onClick={() => onFocusPoint(area.latitude, area.longitude)}
              >
                Show on map
              </button>
            </li>
          );
        })}
      </ul>
    </details>
  );
}
