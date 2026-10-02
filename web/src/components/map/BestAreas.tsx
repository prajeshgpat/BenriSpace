import { useEffect, useId, useRef } from "react";

import type { ApiError } from "@/lib/api/errors";
import { describeError } from "@/lib/api/messages";
import type { FactorKey, MapTopResult } from "@/lib/api/types";
import { scoreColor } from "@/lib/map/colors";
import {
  areaTitle,
  metroLabel,
  strongestFactors,
} from "@/lib/map/presentation";
import { roundScore } from "@/lib/score/presentation";
import type { ResourceStatus } from "@/hooks/useResource";

import styles from "./BestAreas.module.css";

interface BestAreasProps {
  status: ResourceStatus;
  results: readonly MapTopResult[] | null;
  error: ApiError | null;
  /** In display order. */
  selectedFactors: readonly FactorKey[];
  activeGeohash: string | null;
  onSelect: (result: MapTopResult) => void;
  onRetry: () => void;
}

export function BestAreas({
  status,
  results,
  error,
  selectedFactors,
  activeGeohash,
  onSelect,
  onRetry,
}: BestAreasProps) {
  const id = useId();
  const noFactors = selectedFactors.length === 0;

  return (
    <section className={styles.section} aria-labelledby={`${id}-heading`}>
      <h2 id={`${id}-heading`} className={styles.heading}>
        Best areas
      </h2>

      {noFactors ? (
        <p className={styles.message}>
          Select at least one factor to see the best areas.
        </p>
      ) : status === "error" && !results?.length ? (
        <ErrorMessage error={error} onRetry={onRetry} />
      ) : !results ? (
        <p className={styles.message}>Finding the best areas…</p>
      ) : results.length === 0 ? (
        <p className={styles.message}>
          No scored areas in this view. Zoom out or move the map.
        </p>
      ) : (
        <>
          {status === "error" ? (
            <ErrorMessage error={error} onRetry={onRetry} />
          ) : null}
          <ol className={styles.list} aria-busy={status === "loading"}>
            {results.map((result, index) => (
              <AreaItem
                key={result.geohash}
                rank={index + 1}
                result={result}
                selectedFactors={selectedFactors}
                active={result.geohash === activeGeohash}
                onSelect={onSelect}
              />
            ))}
          </ol>
        </>
      )}
    </section>
  );
}

function ErrorMessage({
  error,
  onRetry,
}: {
  error: ApiError | null;
  onRetry: () => void;
}) {
  const { title, body, retryable } = describeError(error?.kind ?? "server");
  return (
    <div className={styles.error}>
      <p>
        <strong>{title}.</strong> {body}
      </p>
      {retryable ? (
        <button type="button" className={styles.retry} onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </div>
  );
}

interface AreaItemProps {
  rank: number;
  result: MapTopResult;
  selectedFactors: readonly FactorKey[];
  active: boolean;
  onSelect: (result: MapTopResult) => void;
}

function AreaItem({
  rank,
  result,
  selectedFactors,
  active,
  onSelect,
}: AreaItemProps) {
  const item = useRef<HTMLLIElement>(null);
  // A marker click can select an entry that is scrolled out of the panel.
  useEffect(() => {
    if (active) item.current?.scrollIntoView?.({ block: "nearest" });
  }, [active]);
  const strongest = strongestFactors(result.subScores, selectedFactors);

  return (
    <li ref={item} className={styles.item} data-active={active || undefined}>
      <button
        type="button"
        className={styles.itemButton}
        aria-pressed={active}
        onClick={() => onSelect(result)}
      >
        <span className={styles.rank} aria-hidden="true">
          {rank}
        </span>
        <span className={styles.itemText}>
          <span className={styles.itemTitle}>
            <span className="sr-only">Rank {rank}: </span>
            {areaTitle(result)}
          </span>
          <span className={styles.itemMeta}>
            {metroLabel(result.metroArea)}
            {strongest.length > 0
              ? ` · Strongest: ${strongest.map((f) => `${f.label} ${f.value}`).join(", ")}`
              : ""}
          </span>
        </span>
        <span className={styles.itemScore}>
          <span
            className={styles.swatch}
            style={{ background: scoreColor(result.score) }}
            aria-hidden="true"
          />
          {roundScore(result.score)}
          <span className="sr-only"> out of 100</span>
        </span>
      </button>
    </li>
  );
}
