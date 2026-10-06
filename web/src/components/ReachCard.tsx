"use client";

import { useEffect, useId, useState, type ReactNode } from "react";

import type { ApiClient } from "@/lib/api/client";
import type { AreaGeometry, ReachMode } from "@/lib/api/types";

import styles from "./ReachCard.module.css";

export interface ReachCardProps {
  /** The scored place; null while none is shown (the control stays, disabled). */
  coordinates: { lat: number; lon: number } | null;
  /** How people here usually travel (from density); walk in the city, else drive. */
  travelMode?: "walk" | "drive" | null;
  client: Pick<ApiClient, "getReach">;
  /** The polygon to draw on the map, or null to clear it. */
  onReach: (geometry: AreaGeometry | null) => void;
}

/** 5, 10, 15 ... up to `max` minutes. */
function everyFive(max: number): readonly number[] {
  return Array.from({ length: max / 5 }, (_, i) => (i + 1) * 5);
}

function Glyph({ children }: { children: ReactNode }) {
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

// Icon paths after Lucide (ISC licence): footprints, train-front, car.
const ICONS: Record<ReachMode, ReactNode> = {
  walk: (
    <Glyph>
      <path d="M4 16v-2.38C4 11.5 2.97 10.5 3 8c.03-2.72 1.49-6 4.5-6C9.37 2 10 3.8 10 5.5c0 3.11-2 5.66-2 8.68V16a2 2 0 1 1-4 0Z" />
      <path d="M20 20v-2.38c0-2.12 1.03-3.12 1-5.62-.03-2.72-1.49-6-4.5-6C14.63 6 14 7.8 14 9.5c0 3.11 2 5.66 2 8.68V20a2 2 0 1 0 4 0Z" />
      <path d="M16 17h4" />
      <path d="M4 13h4" />
    </Glyph>
  ),
  transit: (
    <Glyph>
      <path d="M8 3.1V7a4 4 0 0 0 8 0V3.1" />
      <path d="m9 15-1-1" />
      <path d="m15 15 1-1" />
      <path d="M9 19c-2.8 0-5-2.2-5-5v-4a8 8 0 0 1 16 0v4c0 2.8-2.2 5-5 5Z" />
      <path d="m8 19-2 3" />
      <path d="m16 19 2 3" />
    </Glyph>
  ),
  drive: (
    <Glyph>
      <path d="M19 17h2c.6 0 1-.4 1-1v-3c0-.9-.7-1.7-1.5-1.9C18.7 10.6 16 10 16 10s-1.3-1.4-2.2-2.3c-.5-.4-1.1-.7-1.8-.7H5c-.6 0-1.1.4-1.4.9l-1.4 2.9A3.7 3.7 0 0 0 2 12v4c0 .6.4 1 1 1h2" />
      <circle cx="7" cy="17" r="2" />
      <path d="M9 17h6" />
      <circle cx="17" cy="17" r="2" />
    </Glyph>
  ),
};

/** Every mode steps by 5 minutes: walk and train 5-45, drive 5-60. */
const OPTIONS: ReadonlyArray<{
  mode: ReachMode;
  label: string;
  minutes: readonly number[];
  initial: number;
}> = [
  { mode: "walk", label: "Walk", minutes: everyFive(45), initial: 10 },
  { mode: "transit", label: "Train", minutes: everyFive(45), initial: 20 },
  { mode: "drive", label: "Drive", minutes: everyFive(60), initial: 15 },
];

function optionFor(mode: ReachMode) {
  return OPTIONS.find((o) => o.mode === mode) ?? OPTIONS[2];
}

type State =
  | { status: "off" }
  | { status: "loading" }
  | { status: "ready"; areaSqMi: number; estimate: boolean; empty: boolean }
  | { status: "error" };

/**
 * "How far can I get in N minutes", as one line in the factor controls: an on/off switch,
 * the travel mode and the minutes. It stays mounted while places change, so a switched-on
 * area follows each new place with the same mode and minutes. Until the user picks a mode,
 * the mode follows the place (walking in the city, driving elsewhere).
 */
export function ReachCard({ coordinates, travelMode, client, onReach }: ReachCardProps) {
  const labelId = useId();
  const placeMode: ReachMode = travelMode === "walk" ? "walk" : "drive";
  const [chosen, setChosen] = useState(false);
  const [mode, setMode] = useState<ReachMode>(placeMode);
  const [minutes, setMinutes] = useState(optionFor(placeMode).initial);
  const [seenPlaceMode, setSeenPlaceMode] = useState(placeMode);
  if (travelMode && seenPlaceMode !== placeMode) {
    setSeenPlaceMode(placeMode);
    if (!chosen) {
      setMode(placeMode);
      setMinutes(optionFor(placeMode).initial);
    }
  }
  const [on, setOn] = useState(false);
  const [state, setState] = useState<State>({ status: "off" });
  const lat = coordinates?.lat;
  const lon = coordinates?.lon;

  useEffect(() => {
    if (!on || lat === undefined || lon === undefined) {
      onReach(null);
      setState({ status: "off" });
      return;
    }
    const controller = new AbortController();
    setState({ status: "loading" });
    client
      .getReach(lat, lon, mode, minutes, { signal: controller.signal })
      .then((reach) => {
        onReach(reach.geometry);
        setState({
          status: "ready",
          areaSqMi: reach.areaSqMi,
          estimate: reach.method === "estimate",
          empty: reach.geometry === null,
        });
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        onReach(null);
        setState({ status: "error" });
      });
    return () => controller.abort();
  }, [on, lat, lon, mode, minutes, client, onReach]);

  useEffect(() => () => onReach(null), [onReach]);

  const current = optionFor(mode);
  const step = current.minutes.indexOf(minutes);
  const noPlace = !coordinates;

  return (
    <div className={styles.travel} role="group" aria-labelledby={labelId}>
      <p id={labelId} className={styles.legend}>
        Travel time
      </p>
      <div className={styles.line}>
        <button
          type="button"
          role="switch"
          className={styles.switch}
          aria-checked={on}
          aria-label="Show travel time on the map"
          title={noPlace ? "Pick a place first" : "Show travel time on the map"}
          disabled={noPlace}
          onClick={() => setOn((v) => !v)}
        >
          <span className={styles.thumb} aria-hidden="true" />
        </button>
        <div className={styles.modes} role="group" aria-label="Travel mode">
          {OPTIONS.map((o) => (
            <button
              key={o.mode}
              type="button"
              className={o.mode === mode ? styles.modeOn : styles.mode}
              aria-pressed={o.mode === mode}
              aria-label={o.label}
              title={o.label}
              onClick={() => {
                setChosen(true);
                setMode(o.mode);
                setMinutes(o.initial);
              }}
            >
              {ICONS[o.mode]}
            </button>
          ))}
        </div>
        <div className={styles.stepper} role="group" aria-label="Minutes">
          <button
            type="button"
            className={styles.step}
            aria-label="Fewer minutes"
            disabled={step <= 0}
            onClick={() => {
              setChosen(true);
              setMinutes(current.minutes[Math.max(step - 1, 0)]);
            }}
          >
            &minus;
          </button>
          <span className={styles.value} aria-live="polite">
            {minutes} min
          </span>
          <button
            type="button"
            className={styles.step}
            aria-label="More minutes"
            disabled={step >= current.minutes.length - 1}
            onClick={() => {
              setChosen(true);
              setMinutes(current.minutes[Math.min(step + 1, current.minutes.length - 1)]);
            }}
          >
            +
          </button>
        </div>
      </div>
      {state.status === "loading" ? (
        <p className={styles.meta} role="status">
          Working out the reachable area…
        </p>
      ) : null}
      {state.status === "ready" ? (
        <p className={styles.meta} role="status">
          {state.empty
            ? "Nothing reachable in that time."
            : `About ${state.areaSqMi.toFixed(1)} sq mi within ${minutes} min.`}
          {state.estimate ? " Estimated as a straight-line circle here." : ""}
        </p>
      ) : null}
      {state.status === "error" ? (
        <p className={styles.meta} role="status">
          Couldn&rsquo;t load the reachable area. Try again.
        </p>
      ) : null}
    </div>
  );
}
