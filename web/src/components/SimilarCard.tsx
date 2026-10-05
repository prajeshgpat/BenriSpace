"use client";

import { useId, memo } from "react";

import { useSimilar } from "@/hooks/useSimilar";
import type { ApiClient } from "@/lib/api/client";
import type { PriorityQuery, SimilarDifference } from "@/lib/api/types";
import type { Preview } from "@/lib/map/preview";
import { roundScore } from "@/lib/score/presentation";

import { ShowMoreButton, useShowMore } from "./ShowMore";

import { ReportProblem } from "./Feedback";
import styles from "./SimilarCard.module.css";

export interface SimilarCardProps {
  coordinates: { lat: number; lon: number } | null;
  client: Pick<ApiClient, "getSimilar"> & Partial<Pick<ApiClient, "sendFeedback">>;
  priorities?: PriorityQuery;
  onPreview: (preview: Preview) => void;
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

function SimilarCardImpl({
  coordinates,
  client,
  priorities,
  onPreview,
}: SimilarCardProps) {
  const { status, data, updating } = useSimilar(coordinates, client, priorities);
  const listId = useId();
  const results = (data?.results ?? []).slice(0, MAX_ROWS);
  const { visible, hidden, open, toggle } = useShowMore(results);

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

  if (results.length === 0) return null;

  return (
    <section
      className={styles.card}
      aria-label="Similar areas"
      aria-busy={updating || undefined}
    >
      <div className={styles.summary}>
        <h3 className={styles.title}>Similar areas</h3>
        {updating ? <span className={styles.updating}>Updating…</span> : null}
      </div>
      <ul id={listId} className={styles.list} aria-label="Areas with a similar profile">
        {visible.map((area, index) => {
          const name =
            area.neighborhood ?? area.areaLabel ?? `Area to the ${area.direction}`;
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
                onClick={() =>
                  onPreview({
                    lat: area.latitude,
                    lon: area.longitude,
                    label: name,
                    kind: "similar",
                    summary: {
                      compositeScore: area.compositeScore,
                      differences: area.differences
                        .slice(0, MAX_CHIPS)
                        .map(({ label, delta }) => ({ label, delta })),
                      distanceLabel: area.distanceLabel,
                      direction: area.direction,
                    },
                  })
                }
              >
                Show on map
              </button>
            </li>
          );
        })}
      </ul>
      <ShowMoreButton hidden={hidden} open={open} onToggle={toggle} controls={listId} />
      <ReportProblem client={client} list="Similar areas" />
    </section>
  );
}

/** Skips re-rendering while the map pans and nothing it shows has changed. */
export const SimilarCard = memo(SimilarCardImpl);
