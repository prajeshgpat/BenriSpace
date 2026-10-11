"use client";

import { useEffect, useId, useState } from "react";

import type { ApiClient } from "@/lib/api/client";
import type { AreaGeometry, ReachMode } from "@/lib/api/types";
import { travelOption } from "@/lib/travel";

import styles from "./ReachCard.module.css";

export interface ReachCardProps {
  /** The scored place; null while none is shown (the control stays, disabled). */
  coordinates: { lat: number; lon: number } | null;
  /** The searched place's travel mode and minutes, set in the search box. */
  mode: ReachMode;
  minutes: number;
  client: Pick<ApiClient, "getReach">;
  /** The polygon to draw on the map, or null to clear it. */
  onReach: (geometry: AreaGeometry | null) => void;
  /** True while travel areas are showing for points of interest instead: switch off, no fetch. */
  suspended?: boolean;
}

type State =
  | { status: "off" }
  | { status: "loading" }
  | { status: "ready"; areaSqMi: number; estimate: boolean; empty: boolean }
  | { status: "error" };

/**
 * "How far can I get in N minutes", as one line in the factor controls: an on/off switch for
 * the searched place's travel area. The mode and minutes are set in the search box. It stays
 * mounted while places change, so a switched-on area follows each new place.
 */
export function ReachCard({ coordinates, mode, minutes, client, onReach, suspended }: ReachCardProps) {
  const labelId = useId();
  const [on, setOn] = useState(true);
  const [state, setState] = useState<State>({ status: "off" });
  const lat = coordinates?.lat;
  const lon = coordinates?.lon;

  useEffect(() => {
    if (!on || suspended || lat === undefined || lon === undefined) {
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
  }, [on, suspended, lat, lon, mode, minutes, client, onReach]);

  useEffect(() => () => onReach(null), [onReach]);

  const noPlace = !coordinates;
  const shownOn = on && !suspended;

  return (
    <div className={styles.travel} role="group" aria-labelledby={labelId}>
      <p id={labelId} className={styles.legend}>
        Travel time
      </p>
      <div className={styles.line}>
        <span className={styles.summary}>
          {travelOption(mode).label}, {minutes} min
        </span>
        <button
          type="button"
          role="switch"
          className={styles.switch}
          aria-checked={shownOn}
          aria-label="Show travel time on the map"
          title={noPlace ? "Pick a place first" : "Show travel time on the map"}
          disabled={noPlace || suspended}
          onClick={() => setOn((v) => !v)}
        >
          <span className={styles.thumb} aria-hidden="true" />
        </button>
      </div>
      {suspended ? (
        <p className={styles.note}>Travel areas are showing for your points of interest.</p>
      ) : null}
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
