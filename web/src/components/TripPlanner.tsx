"use client";

import { useEffect, useId, useRef } from "react";

import {
  anchorName,
  type TripPlannerState,
  type TripRow,
} from "@/hooks/useTripPlanner";
import type { ApiClient } from "@/lib/api/client";

import { AddressSearch } from "./AddressSearch";
import styles from "./TripPlanner.module.css";

export const NO_OVERLAP_MESSAGE =
  "These travel areas don't overlap. Try more minutes or a faster mode for one of the places.";

export interface TripPlannerProps {
  planner: TripPlannerState;
  client: Pick<ApiClient, "suggestAddresses">;
  /** A best-area button was pressed: the Workspace navigates there and scores it. */
  onSelectResult: (result: { lat: number; lon: number; label: string }) => void;
  /** "full" when a row is added (room to type), "half" when results arrive. */
  onNeedSpace?: (kind: "full" | "half") => void;
}

interface PointBoxProps {
  row: TripRow;
  /** 1 or 2: the number in the placeholder, label and map. */
  number: number;
  planner: TripPlannerState;
  client: Pick<ApiClient, "suggestAddresses">;
  setInput: (id: string, element: HTMLInputElement | null) => void;
  onRemove: (id: string) => void;
}

/** One very small pill-shaped search box with an x on its right to close it. */
function PointBox({
  row,
  number,
  planner,
  client,
  setInput,
  onRemove,
}: PointBoxProps) {
  const name = `Point of interest ${number}`;
  return (
    <div className={styles.poi} data-slot={number}>
      <AddressSearch
        pill
        label={`${name} address`}
        placeholder={name}
        initialValue={row.label}
        suggestClient={client}
        onSelectSuggestion={(suggestion) =>
          planner.selectSuggestion(row.id, suggestion)
        }
        onTextChange={(text) => planner.setText(row.id, text)}
        onSearch={(text) => {
          if (row.lat !== undefined && text === row.label) return;
          planner.submitText(row.id, text);
        }}
        inputRef={(element) => setInput(row.id, element)}
        endAdornment={
          <button
            type="button"
            className={styles.remove}
            aria-label={`Remove ${name.toLowerCase()}`}
            onClick={() => onRemove(row.id)}
          >
            <svg
              viewBox="0 0 24 24"
              width="12"
              height="12"
              aria-hidden="true"
              focusable="false"
            >
              <path
                d="M6 6l12 12M18 6L6 18"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeLinecap="round"
              />
            </svg>
          </button>
        }
      />
      {row.error ? (
        <p className={styles.error} role="alert">
          {row.error}
        </p>
      ) : null}
    </div>
  );
}

/** Legend swatch: the line style the map uses for this place. */
function Swatch({ index }: { index: number }) {
  return (
    <svg
      className={styles.swatch}
      width="28"
      height="8"
      viewBox="0 0 28 8"
      aria-hidden="true"
      data-index={index}
    >
      <line x1="1" y1="4" x2="27" y2="4" strokeWidth="3" strokeLinecap="butt" />
    </svg>
  );
}

function areasFound(count: number): string {
  return `${count} ${count === 1 ? "area" : "areas"} found in the overlap`;
}

/**
 * "+ Point of interest": up to two small search boxes next to the pill, and the areas
 * where the searched place's and their travel areas overlap (all use the Travel time row). State lives in
 * `useTripPlanner`; the Workspace owns the hook so the map and URL can follow.
 */
export function TripPlanner({
  planner,
  client,
  onSelectResult,
  onNeedSpace,
}: TripPlannerProps) {
  const rootId = useId();
  const { rows, status, data } = planner;
  const inputs = useRef(new Map<string, HTMLInputElement>());
  const addButton = useRef<HTMLButtonElement>(null);
  const focusAdd = useRef(false);
  const handledAdd = useRef(planner.lastAddedId);
  const previousRows = useRef(rows.length);
  const previousStatus = useRef(status);

  const setInput = (id: string, element: HTMLInputElement | null) => {
    if (element) inputs.current.set(id, element);
    else inputs.current.delete(id);
  };

  // Focus follows an added row's input, and returns to the add button on removal.
  useEffect(() => {
    if (
      planner.lastAddedId !== null &&
      planner.lastAddedId !== handledAdd.current
    ) {
      handledAdd.current = planner.lastAddedId;
      inputs.current.get(planner.lastAddedId)?.focus();
    } else if (focusAdd.current && rows.length < previousRows.current) {
      addButton.current?.focus();
    }
    focusAdd.current = false;
    if (rows.length > previousRows.current) onNeedSpace?.("full");
    previousRows.current = rows.length;
  }, [rows.length, planner.lastAddedId, onNeedSpace]);

  useEffect(() => {
    const arrived =
      (status === "ready" || status === "empty") &&
      previousStatus.current !== status;
    previousStatus.current = status;
    if (arrived) onNeedSpace?.("half");
  }, [status, onNeedSpace]);

  const live =
    status === "ready" && data
      ? areasFound(data.results.length)
      : status === "empty"
        ? NO_OVERLAP_MESSAGE
        : "";

  return (
    <section className={styles.root} aria-label="Points of interest">
      <div className={styles.pills}>
        {rows.length > 0 ? (
          <div className={styles.boxes}>
            {rows.map((row, index) => (
              <PointBox
                key={row.id}
                row={row}
                number={index + 1}
                planner={planner}
                client={client}
                setInput={setInput}
                onRemove={(id) => {
                  focusAdd.current = true;
                  planner.remove(id);
                }}
              />
            ))}
          </div>
        ) : null}
        {planner.canAdd ? (
          <button
            ref={addButton}
            type="button"
            className={styles.add}
            onClick={planner.add}
          >
            <span aria-hidden="true">+ </span>Point of interest
          </button>
        ) : null}
      </div>

      {rows.some((row) => row.lat !== undefined) ? (
        <ul className={styles.legend2} aria-label="Map legend">
          {[
            0,
            ...rows.flatMap((row, i) => (row.lat !== undefined ? [i + 1] : [])),
          ].map((index) => (
            <li key={index} className={styles.legendItem} data-index={index}>
              <Swatch index={index} />
              {anchorName(index)}
            </li>
          ))}
          <li className={styles.legendItem} data-overlap="true">
            <span className={styles.overlapSwatch} aria-hidden="true" />
            Overlap
          </li>
        </ul>
      ) : null}

      <p className="sr-only" role="status" aria-live="polite">
        {live}
      </p>

      {status === "loading" ? (
        <p className={styles.meta}>Working out the overlap&hellip;</p>
      ) : null}

      {status === "error" ? (
        <div className={styles.meta}>
          <p>Couldn&rsquo;t work out the overlap.</p>
          <button
            type="button"
            className={styles.retry}
            onClick={planner.retry}
          >
            Retry
          </button>
        </div>
      ) : null}

      {status === "empty" ? (
        <p className={styles.meta}>{NO_OVERLAP_MESSAGE}</p>
      ) : null}

      {status === "ready" && data ? (
        <div className={styles.results}>
          <h3 id={`${rootId}-results`} className={styles.heading}>
            Best areas in the overlap
          </h3>
          <ol className={styles.list} aria-labelledby={`${rootId}-results`}>
            {data.results.map((result) => (
              <li key={`${result.lat},${result.lon}`}>
                <button
                  type="button"
                  className={styles.result}
                  onClick={() =>
                    onSelectResult({
                      lat: result.lat,
                      lon: result.lon,
                      label: result.label,
                    })
                  }
                >
                  <span className={styles.resultLabel}>{result.label}</span>
                  <span className={styles.resultScore}>
                    {Math.round(result.score)}
                  </span>
                </button>
              </li>
            ))}
          </ol>
          {data.estimate ? (
            <p className={styles.meta}>
              At least one travel area is a straight-line estimate, not road
              routing.
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
