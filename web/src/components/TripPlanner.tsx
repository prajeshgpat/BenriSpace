"use client";

import { useEffect, useId, useRef, useState, type Ref } from "react";

import {
  effectiveTravel,
  type TripPlannerState,
  type TripRow,
  type TripTravel,
} from "@/hooks/useTripPlanner";
import type { ApiClient } from "@/lib/api/client";
import type { ReachMode } from "@/lib/api/types";
import { TRAVEL_OPTIONS, travelOption } from "@/lib/travel";

import { AddressSearch } from "./AddressSearch";
import { MinutesStepper, TravelModeIcon } from "./TravelModePicker";
import styles from "./TripPlanner.module.css";

export const NO_OVERLAP_MESSAGE =
  "These travel areas don't overlap. Try more minutes or a faster mode for one of the places.";

/** Shown in a box that is waiting for a place to be tapped on the map. */
export const ARMED_PLACEHOLDER = "Drop a pin";
/** Used until the main Travel time row has reported its value. */
const FALLBACK_TRAVEL: TripTravel = { mode: "drive", minutes: 15 };

export interface TripResultPick {
  lat: number;
  lon: number;
  label: string;
  score: number;
}

export interface TripPlannerPillsProps {
  planner: TripPlannerState;
  client: Pick<ApiClient, "suggestAddresses">;
  /** "half" when a row is added: the map stays in view so a pin can be dropped on it. */
  onNeedSpace?: (kind: "full" | "half") => void;
}

export interface TripResultsProps {
  planner: TripPlannerState;
  /** A best-area button was pressed: the Workspace previews it on the map. */
  onSelectResult: (result: TripResultPick) => void;
  /** Attached to the section while it shows, so the sheet's middle snap can end under it. */
  sectionRef?: Ref<HTMLElement>;
  /** `lat,lon` of the result being previewed, if any. */
  selectedKey?: string | null;
  /** "half" when results arrive. */
  onNeedSpace?: (kind: "full" | "half") => void;
}

export interface TripPlannerProps
  extends TripPlannerPillsProps,
    Omit<TripResultsProps, "onNeedSpace"> {}

/** The key a result is matched by to know it is the one on show. */
export function resultKey(result: { lat: number; lon: number }): string {
  return `${result.lat},${result.lon}`;
}

interface PointBoxProps {
  row: TripRow;
  /** 1 or 2: the number in the placeholder, label and map. */
  number: number;
  planner: TripPlannerState;
  client: Pick<ApiClient, "suggestAddresses">;
  open: boolean;
  onToggle: () => void;
  setInput: (id: string, element: HTMLInputElement | null) => void;
  onRemove: (id: string) => void;
}

/**
 * One point of interest as a pill: the travel mode on the left (tap to open a list of the
 * other modes and the minutes), the place on the right, and an x to remove it.
 */
function PointBox({
  row,
  number,
  planner,
  client,
  open,
  onToggle,
  setInput,
  onRemove,
}: PointBoxProps) {
  const name = `Point of interest ${number}`;
  const panelId = useId();
  const armed = planner.armedId === row.id;
  const { mode, minutes } = effectiveTravel(row, planner.travel ?? FALLBACK_TRAVEL);
  const current = travelOption(mode);
  const others = TRAVEL_OPTIONS.filter((o) => o.mode !== mode);
  const inputElement = useRef<HTMLInputElement | null>(null);

  const choose = (next: ReachMode, nextMinutes: number) =>
    planner.setTravel(row.id, next, nextMinutes);

  return (
    <div
      className={styles.poi}
      data-slot={number}
      data-poi-box={row.id}
      data-open={open || undefined}
      data-armed={armed || undefined}
      // The input is the real control: focusing it by any route makes this box the one
      // a map tap fills.
      onFocus={(event) => {
        if (event.target === inputElement.current) planner.arm(row.id);
      }}
    >
      <div className={styles.pill}>
        <div className={styles.modeCol}>
          <button
            type="button"
            className={styles.modeToggle}
            aria-expanded={open}
            aria-controls={panelId}
            aria-label={`Travel for ${name}: ${current.label}, ${minutes} minutes`}
            onClick={onToggle}
          >
            <span className={styles.modeIcon} aria-hidden="true">
              <TravelModeIcon mode={mode} />
            </span>
            <svg
              className={styles.chevron}
              viewBox="0 0 24 24"
              width="14"
              height="14"
              aria-hidden="true"
              focusable="false"
            >
              <path
                d="M9 6l6 6-6 6"
                fill="none"
                stroke="currentColor"
                strokeWidth="3"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
          {open ? (
            <div
              className={styles.modeList}
              role="group"
              aria-label={`Travel mode for ${name}`}
            >
              {others.map((o) => (
                <button
                  key={o.mode}
                  type="button"
                  className={styles.modeOption}
                  aria-pressed={false}
                  aria-label={o.label}
                  title={o.label}
                  onClick={() => choose(o.mode, o.initial)}
                >
                  <TravelModeIcon mode={o.mode} />
                </button>
              ))}
            </div>
          ) : null}
        </div>
        <div id={panelId} className={styles.main}>
          <div className={styles.textWrap}>
            <AddressSearch
              pill
              bare
              label={`${name} address`}
              placeholder={armed ? ARMED_PLACEHOLDER : name}
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
              inputRef={(element) => {
                inputElement.current = element;
                setInput(row.id, element);
              }}
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
            {/* Covers the input until it is armed: a tap on an input would open the phone's
                keyboard (and zoom), but the first tap is meant to arm the box so a pin can be
                dropped on the map. The second tap focuses the input in the same gesture, which
                is what lets iOS open the keyboard. Keyboard users reach the input directly. */}
            <div
              className={styles.tapGuard}
              aria-hidden="true"
              data-testid={`poi-tap-${number}`}
              onClick={() => {
                if (armed) inputElement.current?.focus();
                else planner.arm(row.id);
              }}
            />
          </div>
          {open ? (
            <MinutesStepper
              className={styles.minutes}
              mode={mode}
              minutes={minutes}
              onChange={choose}
              label={`Minutes for ${name}`}
              fewerLabel={`Fewer minutes for ${name}`}
              moreLabel={`More minutes for ${name}`}
            />
          ) : null}
        </div>
      </div>
      {row.error ? (
        <p className={styles.error} role="alert">
          {row.error}
        </p>
      ) : null}
    </div>
  );
}

function areasFound(count: number): string {
  return `${count} ${count === 1 ? "area" : "areas"} found in the overlap`;
}

/**
 * "+ Point of interest": up to two pills (travel mode, place, x) and the add pill. These stay
 * on screen when the sheet is collapsed; the results come from `TripResults`.
 */
export function TripPlannerPills({ planner, client, onNeedSpace }: TripPlannerPillsProps) {
  const { rows } = planner;
  const inputs = useRef(new Map<string, HTMLInputElement>());
  const addButton = useRef<HTMLButtonElement>(null);
  const root = useRef<HTMLElement>(null);
  const focusAdd = useRef(false);
  const previousRows = useRef(rows.length);
  const [openId, setOpenId] = useState<string | null>(null);
  const { armedId, arm } = planner;

  const setInput = (id: string, element: HTMLInputElement | null) => {
    if (element) inputs.current.set(id, element);
    else inputs.current.delete(id);
  };

  useEffect(() => {
    if (focusAdd.current && rows.length < previousRows.current) {
      addButton.current?.focus();
    }
    focusAdd.current = false;
    // Half, not full: the map stays in view so a place can be tapped on it to fill the box.
    if (rows.length > previousRows.current) onNeedSpace?.("half");
    previousRows.current = rows.length;
  }, [rows.length, onNeedSpace]);

  // A press elsewhere in the sheet un-arms the box, and anywhere outside closes a dropdown.
  // A press on the map is left alone: the click that follows it fills the armed box.
  const dropdownOpen = openId !== null && rows.some((row) => row.id === openId);
  useEffect(() => {
    if (armedId === null && !dropdownOpen) return;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target instanceof Element ? event.target : null;
      if (!target) return;
      const box = target.closest("[data-poi-box]");
      if (dropdownOpen && box?.getAttribute("data-poi-box") !== openId) {
        setOpenId(null);
      }
      if (armedId !== null && box?.getAttribute("data-poi-box") !== armedId) {
        const inSheet = target.closest('[aria-label="Search and map controls"]');
        if (inSheet) arm(null);
      }
    };
    document.addEventListener("pointerdown", onPointerDown, true);
    return () => document.removeEventListener("pointerdown", onPointerDown, true);
  }, [armedId, dropdownOpen, openId, arm]);

  return (
    <section ref={root} className={styles.root} aria-label="Points of interest">
      <div className={styles.pills}>
        {rows.map((row, index) => (
          <PointBox
            key={row.id}
            row={row}
            number={index + 1}
            planner={planner}
            client={client}
            open={openId === row.id}
            onToggle={() => setOpenId((current) => (current === row.id ? null : row.id))}
            setInput={setInput}
            onRemove={(id) => {
              focusAdd.current = true;
              planner.remove(id);
            }}
          />
        ))}
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
    </section>
  );
}

/** Status, errors and "Best areas in the overlap" for the planner's places. */
export function TripResults({
  planner,
  onSelectResult,
  selectedKey = null,
  sectionRef,
  onNeedSpace,
}: TripResultsProps) {
  const rootId = useId();
  const { status, data } = planner;
  const previousStatus = useRef(status);

  useEffect(() => {
    const arrived =
      (status === "ready" || status === "empty") &&
      previousStatus.current !== status;
    previousStatus.current = status;
    if (arrived) onNeedSpace?.("half");
  }, [status, onNeedSpace]);

  if (status === "idle") return null;

  const live =
    status === "ready" && data
      ? areasFound(data.results.length)
      : status === "empty"
        ? NO_OVERLAP_MESSAGE
        : "";

  return (
    <section ref={sectionRef} className={styles.outcome} aria-label="Overlap results">
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
        <div className={styles.results} data-overlap-results>
          <h3 id={`${rootId}-results`} className={styles.heading}>
            Best areas in the overlap
          </h3>
          <ol className={styles.list} aria-labelledby={`${rootId}-results`}>
            {data.results.map((result) => {
              const selected = selectedKey === resultKey(result);
              return (
                <li key={resultKey(result)}>
                  <button
                    type="button"
                    className={styles.result}
                    aria-pressed={selected}
                    data-active={selected || undefined}
                    onClick={() =>
                      onSelectResult({
                        lat: result.lat,
                        lon: result.lon,
                        label: result.label,
                        score: result.score,
                      })
                    }
                  >
                    <span className={styles.resultLabel}>{result.label}</span>
                    <span className={styles.resultScore}>
                      {Math.round(result.score)}
                    </span>
                  </button>
                </li>
              );
            })}
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

/** Pills and results together (the desktop panel and the tests). */
export function TripPlanner({
  planner,
  client,
  onSelectResult,
  selectedKey,
  sectionRef,
  onNeedSpace,
}: TripPlannerProps) {
  return (
    <>
      <TripPlannerPills planner={planner} client={client} onNeedSpace={onNeedSpace} />
      <TripResults
        planner={planner}
        onSelectResult={onSelectResult}
        selectedKey={selectedKey}
        sectionRef={sectionRef}
        onNeedSpace={onNeedSpace}
      />
    </>
  );
}
