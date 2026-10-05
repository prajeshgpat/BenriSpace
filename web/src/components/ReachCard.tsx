"use client";

import { useEffect, useState } from "react";

import type { ApiClient } from "@/lib/api/client";
import type { AreaGeometry, ReachMode } from "@/lib/api/types";

import styles from "./ReachCard.module.css";

export interface ReachCardProps {
  coordinates: { lat: number; lon: number } | null;
  client: Pick<ApiClient, "getReach">;
  /** The polygon to draw on the map, or null to clear it. */
  onReach: (geometry: AreaGeometry | null) => void;
}

const OPTIONS: ReadonlyArray<{
  mode: ReachMode;
  label: string;
  minutes: readonly number[];
}> = [
  { mode: "walk", label: "Walk", minutes: [10, 15, 20, 30] },
  { mode: "drive", label: "Drive", minutes: [15, 30, 45, 60] },
  { mode: "transit", label: "Train", minutes: [30, 45, 60, 90] },
];

type State =
  | { status: "off" }
  | { status: "loading" }
  | { status: "ready"; areaSqMi: number; estimate: boolean; empty: boolean }
  | { status: "error" };

/** "How far can I get in N minutes": draws the reachable area on the map. */
export function ReachCard({ coordinates, client, onReach }: ReachCardProps) {
  const [mode, setMode] = useState<ReachMode>("drive");
  const [minutes, setMinutes] = useState(30);
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
  const current = OPTIONS.find((o) => o.mode === mode) ?? OPTIONS[1];

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
              setMinutes(o.minutes[1]);
            }}
          >
            {o.label}
          </button>
        ))}
      </div>
      <div className={styles.row} role="group" aria-label="Minutes">
        {current.minutes.map((m) => (
          <button
            key={m}
            type="button"
            className={m === minutes ? styles.chipOn : styles.chip}
            aria-pressed={m === minutes}
            onClick={() => setMinutes(m)}
          >
            {m} min
          </button>
        ))}
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
