"use client";

import { useEffect, useState } from "react";

import type { ApiClient } from "@/lib/api/client";
import type { AreaGeometry, ReachMode } from "@/lib/api/types";

import styles from "./ReachCard.module.css";

export interface ReachCardProps {
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

/** "How far can I get in N minutes": draws the reachable area on the map. */
export function ReachCard({ coordinates, travelMode, client, onReach }: ReachCardProps) {
  const startMode: ReachMode = travelMode === "walk" ? "walk" : "drive";
  const [mode, setMode] = useState<ReachMode>(startMode);
  const [minutes, setMinutes] = useState(optionFor(startMode).initial);
  // A new place starts from its own default: walking in the city, driving elsewhere.
  const [seenMode, setSeenMode] = useState(startMode);
  if (seenMode !== startMode) {
    setSeenMode(startMode);
    setMode(startMode);
    setMinutes(optionFor(startMode).initial);
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

  if (!coordinates) return null;
  const current = optionFor(mode);
  const step = current.minutes.indexOf(minutes);

  return (
    <section className={styles.card} aria-label="Reachable area">
      <div className={styles.summary}>
        <h3 className={styles.title}>How far can I get?</h3>
        <button
          type="button"
          className={styles.toggle}
          aria-pressed={on}
          onClick={() => setOn((v) => !v)}
        >
          {on ? "Hide on map" : "Show on map"}
        </button>
      </div>
      <div className={styles.row} role="group" aria-label="Travel mode">
        {OPTIONS.map((o) => (
          <button
            key={o.mode}
            type="button"
            className={o.mode === mode ? styles.chipOn : styles.chip}
            aria-pressed={o.mode === mode}
            onClick={() => {
              setMode(o.mode);
              setMinutes(o.initial);
            }}
          >
            {o.label}
          </button>
        ))}
      </div>
      <div className={styles.stepper} role="group" aria-label="Minutes">
        <button
          type="button"
          className={styles.step}
          aria-label="Fewer minutes"
          disabled={step <= 0}
          onClick={() => setMinutes(current.minutes[Math.max(step - 1, 0)])}
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
          onClick={() =>
            setMinutes(current.minutes[Math.min(step + 1, current.minutes.length - 1)])
          }
        >
          +
        </button>
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
          {state.estimate
            ? " Estimated as a straight-line circle: road routing is not computed for this area yet."
            : ""}
        </p>
      ) : null}
      {state.status === "error" ? (
        <p className={styles.meta} role="status">
          Couldn&rsquo;t load the reachable area. Try again.
        </p>
      ) : null}
    </section>
  );
}
