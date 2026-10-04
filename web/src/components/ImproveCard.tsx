"use client";

import { useId } from "react";

import { useImprove } from "@/hooks/useImprove";
import type { ApiClient } from "@/lib/api/client";
import type { PriorityQuery } from "@/lib/api/types";
import { FactorIcon } from "@/lib/factorIcons";
import type { Preview } from "@/lib/map/preview";
import { roundScore } from "@/lib/score/presentation";

import { ShowMoreButton, useShowMore } from "./ShowMore";

import styles from "./ImproveCard.module.css";

export interface ImproveCardProps {
  coordinates: { lat: number; lon: number } | null;
  client: Pick<ApiClient, "getImprove">;
  priorities?: PriorityQuery;
  onPreview: (preview: Preview) => void;
}

function signed(value: number): string {
  const rounded = roundScore(value);
  return `${rounded >= 0 ? "+" : "−"}${Math.abs(rounded)}`;
}

export function ImproveCard({ coordinates, client, priorities, onPreview }: ImproveCardProps) {
  const { status, data, updating } = useImprove(coordinates, client, priorities);
  const listId = useId();
  const { visible, hidden, open, toggle } = useShowMore(data?.suggestions ?? []);

  if (status === "idle" || status === "unavailable") return null;

  if (status === "loading" || !data) {
    return (
      <section
        className={styles.card}
        aria-label="Improve this area"
        aria-busy="true"
        data-testid="improve-skeleton"
      >
        <span className={styles.skeleton} />
        <span className={styles.skeleton} />
      </section>
    );
  }

  if (data.suggestions.length === 0 && !data.bestNearby) return null;
  const best = data.bestNearby;

  return (
    <section
      className={styles.card}
      aria-label="Improve this area"
      aria-busy={updating || undefined}
    >
      <div className={styles.summary}>
        <h3 className={styles.title}>Improve this area</h3>
        {updating ? <span className={styles.updating}>Updating…</span> : null}
      </div>
      {best ? (
        <p className={styles.best}>
          <span>
            <strong>Best move nearby:</strong>{" "}
            {best.neighborhood ? `${best.neighborhood}, ` : ""}
            {signed(best.compositeGain)} overall, {best.distanceLabel} {best.direction}
          </span>
          <button
            type="button"
            className={styles.action}
            aria-label={`Show best move nearby on map`}
            onClick={() =>
              onPreview({
                lat: best.latitude,
                lon: best.longitude,
                label: best.neighborhood ?? "Best move nearby",
                subtitle: best.neighborhood ? "Best move nearby" : undefined,
                kind: "best-move",
                summary: {
                  compositeScore: best.compositeScore,
                  distanceLabel: best.distanceLabel,
                  direction: best.direction,
                },
              })
            }
          >
            Show on map
          </button>
        </p>
      ) : null}
      <ul id={listId} className={styles.list}>
        {visible.map((s) => (
          <li key={s.factor} className={styles.item} data-factor={s.factor}>
            <p className={styles.head}>
              <FactorIcon factor={s.factor} />
              <span className={styles.label}>{s.label}</span>
              <span className={styles.score}>{roundScore(s.score)}</span>
            </p>
            <p className={styles.tip}>{s.tip}</p>
            {s.places.length > 0 ? (
              <ul className={styles.places} aria-label={`Nearby ${s.label}`}>
                {s.places.slice(0, 3).map((place, i) => (
                  <li key={`${place.name}-${i}`}>
                    {place.name} &middot; {place.distanceLabel} &middot;{" "}
                    {place.direction}
                  </li>
                ))}
              </ul>
            ) : null}
            {s.betterArea?.neighborhood ? (
              <p className={styles.betterArea}>
                Better area: {s.betterArea.neighborhood} &middot;{" "}
                {s.betterArea.distanceLabel} {s.betterArea.direction}
              </p>
            ) : null}
            {s.betterArea ? (
              <button
                type="button"
                className={styles.action}
                aria-label={`Show better area for ${s.label} on map`}
                onClick={() => {
                  const area = s.betterArea!;
                  onPreview({
                    lat: area.latitude,
                    lon: area.longitude,
                    label: area.neighborhood ?? `Better area for ${s.label}`,
                    subtitle: area.neighborhood
                      ? `Better area for ${s.label}`
                      : undefined,
                    kind: "improve",
                    summary: {
                      compositeScore: area.compositeScore,
                      distanceLabel: area.distanceLabel,
                      direction: area.direction,
                    },
                  });
                }}
              >
                Show on map
              </button>
            ) : null}
          </li>
        ))}
      </ul>
      <ShowMoreButton hidden={hidden} open={open} onToggle={toggle} controls={listId} />
    </section>
  );
}
