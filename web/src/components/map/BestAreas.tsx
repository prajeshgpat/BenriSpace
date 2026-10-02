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
import type { TopScope } from "@/lib/map/url";
import { FACTORS } from "@/lib/score/factors";
import { roundScore } from "@/lib/score/presentation";
import type { ResourceStatus } from "@/hooks/useResource";

import { AreaDetails } from "./AreaDetails";
import styles from "./BestAreas.module.css";

interface BestAreasProps {
  status: ResourceStatus;
  results: readonly MapTopResult[] | null;
  error: ApiError | null;
  /** In display order. */
  selectedFactors: readonly FactorKey[];
  scope: TopScope;
  onScopeChange: (scope: TopScope) => void;
  activeGeohash: string | null;
  onSelect: (result: MapTopResult) => void;
  onRetry: () => void;
}

const SCOPES: ReadonlyArray<{ value: TopScope; label: string }> = [
  { value: "metro", label: "Whole metro" },
  { value: "view", label: "This view only" },
];

export function BestAreas({
  status,
  results,
  error,
  selectedFactors,
  scope,
  onScopeChange,
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

      <fieldset className={styles.scope}>
        <legend className="sr-only">Where to look</legend>
        {SCOPES.map(({ value, label }) => (
          <label key={value} className={styles.scopeOption}>
            <input
              type="radio"
              name={`${id}-scope`}
              value={value}
              checked={scope === value}
              onChange={() => onScopeChange(value)}
            />
            <span>{label}</span>
          </label>
        ))}
      </fieldset>

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
          {scope === "view"
            ? "No scored areas in this view. Zoom out or switch to the whole metro."
            : "No scored areas found for these factors."}
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
  const detailsId = useId();
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
        aria-expanded={active}
        aria-controls={detailsId}
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
      <div id={detailsId} hidden={!active} className={styles.details}>
        {active ? (
          <AreaDetails
            score={result.score}
            basis={`${selectedFactors.length} selected ${selectedFactors.length === 1 ? "factor" : "factors"}`}
            rows={selectedFactors.map((key) => ({
              key,
              label: FACTORS[key].label,
              value: result.subScores[key],
            }))}
            lat={result.latitude}
            lon={result.longitude}
          />
        ) : null}
      </div>
    </li>
  );
}
