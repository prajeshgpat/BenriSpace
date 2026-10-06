"use client";

import { useEffect, useRef, type ReactNode } from "react";

import {
  anchorName,
  type TripPlannerState,
  type TripRow,
} from "@/hooks/useTripPlanner";
import type { ApiClient } from "@/lib/api/client";
import type { ReachMode } from "@/lib/api/types";

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

/** The temporary mode/minutes interface; swap for `TravelModePicker` (P1) later. */
interface TravelValue {
  mode: ReachMode;
  minutes: number;
}

interface TravelControlProps extends TravelValue {
  name: string;
  onChange: (value: TravelValue) => void;
}

function everyFive(max: number): readonly number[] {
  return Array.from({ length: max / 5 }, (_, i) => (i + 1) * 5);
}

const MODES: ReadonlyArray<{
  mode: ReachMode;
  label: string;
  minutes: readonly number[];
  initial: number;
}> = [
  { mode: "walk", label: "Walk", minutes: everyFive(45), initial: 10 },
  { mode: "transit", label: "Train", minutes: everyFive(45), initial: 20 },
  { mode: "drive", label: "Drive", minutes: everyFive(60), initial: 15 },
];

function svg(children: ReactNode) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={18}
      height={18}
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

const MODE_ICONS: Record<ReachMode, ReactNode> = {
  // A walking person.
  walk: svg(
    <>
      <circle cx="13" cy="4" r="1.5" />
      <path d="M13 7.5 11 12l3 3 1 6" />
      <path d="m11 12-2 3-3 1" />
      <path d="m10 9-3 2" />
      <path d="m13 8 3 2h2" />
      <path d="m11 12-1 9" />
    </>,
  ),
  transit: svg(
    <>
      <rect x="5" y="3" width="14" height="14" rx="3" />
      <path d="M5 11h14" />
      <path d="m8 21 2-4M16 21l-2-4" />
      <path d="M9 14h.01M15 14h.01" />
    </>,
  ),
  drive: svg(
    <>
      <path d="M5 16V11l2-5h10l2 5v5" />
      <path d="M3 16h18v3H3z" />
      <path d="M7 13h.01M17 13h.01" />
    </>,
  ),
};

function TravelControl({ name, mode, minutes, onChange }: TravelControlProps) {
  const current = MODES.find((m) => m.mode === mode) ?? MODES[2];
  const step = current.minutes.indexOf(minutes);
  const move = (delta: number) => {
    const next = current.minutes[Math.min(Math.max(step + delta, 0), current.minutes.length - 1)];
    onChange({ mode, minutes: next });
  };
  return (
    <div className={styles.travel}>
      <div className={styles.modes} role="group" aria-label={`Travel mode for ${name}`}>
        {MODES.map((m) => (
          <button
            key={m.mode}
            type="button"
            className={styles.mode}
            aria-label={m.label}
            aria-pressed={m.mode === mode}
            onClick={() =>
              m.mode !== mode && onChange({ mode: m.mode, minutes: m.initial })
            }
          >
            {MODE_ICONS[m.mode]}
          </button>
        ))}
      </div>
      <div className={styles.stepper} role="group" aria-label={`Minutes for ${name}`}>
        <button
          type="button"
          className={styles.step}
          aria-label={`Fewer minutes for ${name}`}
          disabled={step <= 0}
          onClick={() => move(-1)}
        >
          &minus;
        </button>
        <span className={styles.minutes}>{minutes} min</span>
        <button
          type="button"
          className={styles.step}
          aria-label={`More minutes for ${name}`}
          disabled={step >= current.minutes.length - 1}
          onClick={() => move(1)}
        >
          +
        </button>
      </div>
    </div>
  );
}

const BADGES = ["★", "1", "2"];

function Badge({ index }: { index: number }) {
  return (
    <span className={styles.badge} data-index={index} aria-hidden="true">
      {BADGES[index]}
    </span>
  );
}

interface RowFieldsProps {
  row: TripRow;
  index: number;
  planner: TripPlannerState;
  client: Pick<ApiClient, "suggestAddresses">;
  setInput: (id: string, element: HTMLInputElement | null) => void;
  onRemove: (id: string) => void;
}

function RowFields({ row, index, planner, client, setInput, onRemove }: RowFieldsProps) {
  const name = anchorName(index);
  return (
    <fieldset className={styles.row} data-index={index}>
      <legend className={styles.legend}>
        <Badge index={index} />
        <span>{name}</span>
      </legend>
      <button
        type="button"
        className={styles.remove}
        aria-label={`Remove ${name}`}
        onClick={() => onRemove(row.id)}
      >
        &times;
      </button>
      <AddressSearch
        compact
        label={`${name} address`}
        placeholder={index === 0 ? "Your place" : "Add an address"}
        initialValue={row.label}
        suggestClient={client}
        onSelectSuggestion={(suggestion) => planner.selectSuggestion(row.id, suggestion)}
        onSearch={(text) => {
          if (row.lat !== undefined && text === row.label) return;
          planner.submitText(row.id, text);
        }}
        onClear={() => planner.clearPlace(row.id)}
        inputRef={(element) => setInput(row.id, element)}
      />
      {row.error ? (
        <p className={styles.error} role="alert">
          {row.error}
        </p>
      ) : null}
      <TravelControl
        name={name}
        mode={row.mode}
        minutes={row.minutes}
        onChange={(travel) => planner.setTravel(row.id, travel)}
      />
    </fieldset>
  );
}

/** Legend swatch: the line style the map uses for this place. */
function Swatch({ index }: { index: number }) {
  return (
    <svg className={styles.swatch} width="28" height="8" viewBox="0 0 28 8" aria-hidden="true" data-index={index}>
      <line x1="1" y1="4" x2="27" y2="4" strokeWidth="3" strokeLinecap="butt" />
    </svg>
  );
}

function areasFound(count: number): string {
  return `${count} ${count === 1 ? "area" : "areas"} found in the overlap`;
}

/**
 * "+ Point of interest": up to two extra places, each with a travel mode and time,
 * and the areas where all their travel areas overlap. State lives in
 * `useTripPlanner`; the Workspace owns the hook so the map and URL can follow.
 */
export function TripPlanner({ planner, client, onSelectResult, onNeedSpace }: TripPlannerProps) {
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
    if (planner.lastAddedId !== null && planner.lastAddedId !== handledAdd.current) {
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

      {rows.map((row, index) => (
        <RowFields
          key={row.id}
          row={row}
          index={index}
          planner={planner}
          client={client}
          setInput={setInput}
          onRemove={(id) => {
            focusAdd.current = true;
            planner.remove(id);
          }}
        />
      ))}

      {rows.length > 0 ? (
        <ul className={styles.legend2} aria-label="Map legend">
          {rows.map((row, index) => (
            <li key={row.id} className={styles.legendItem} data-index={index}>
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
          <button type="button" className={styles.retry} onClick={planner.retry}>
            Retry
          </button>
        </div>
      ) : null}

      {status === "empty" ? <p className={styles.meta}>{NO_OVERLAP_MESSAGE}</p> : null}

      {status === "ready" && data ? (
        <div className={styles.results}>
          <h3 className={styles.heading}>Best areas in the overlap</h3>
          <ol className={styles.list}>
            {data.results.map((result) => (
              <li key={`${result.lat},${result.lon}`}>
                <button
                  type="button"
                  className={styles.result}
                  onClick={() =>
                    onSelectResult({ lat: result.lat, lon: result.lon, label: result.label })
                  }
                >
                  <span className={styles.resultLabel}>{result.label}</span>
                  <span className={styles.resultScore}>{Math.round(result.score)}</span>
                </button>
              </li>
            ))}
          </ol>
          {data.estimate ? (
            <p className={styles.meta}>
              At least one travel area is a straight-line estimate, not road routing.
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
