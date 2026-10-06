"use client";

import { useEffect, useId, useState } from "react";

import type { ApiClient } from "@/lib/api/client";
import type { AreaGeometry, ReachMode } from "@/lib/api/types";
import { defaultTravel } from "@/lib/travel";

import styles from "./ReachCard.module.css";
import { TravelModePicker } from "./TravelModePicker";

export interface ReachCardProps {
  /** The scored place; null while none is shown (the control stays, disabled). */
  coordinates: { lat: number; lon: number } | null;
  /** How people here usually travel (from density); walk in the city, else drive. */
  travelMode?: "walk" | "drive" | null;
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
 * "How far can I get in N minutes", as one line in the factor controls: an on/off switch,
 * the travel mode and the minutes. It stays mounted while places change, so a switched-on
 * area follows each new place with the same mode and minutes. Until the user picks a mode,
 * the mode follows the place (a 20 min train in dense places, a 15 min drive elsewhere).
 */
export function ReachCard({ coordinates, travelMode, client, onReach, suspended }: ReachCardProps) {
  const labelId = useId();
  const placeDefault = defaultTravel(travelMode);
  const placeKey = travelMode === "walk" ? "walk" : "drive";
  const [chosen, setChosen] = useState(false);
  const [mode, setMode] = useState<ReachMode>(placeDefault.mode);
  const [minutes, setMinutes] = useState(placeDefault.minutes);
  const [seenPlaceKey, setSeenPlaceKey] = useState(placeKey);
  if (travelMode && seenPlaceKey !== placeKey) {
    setSeenPlaceKey(placeKey);
    if (!chosen) {
      setMode(placeDefault.mode);
      setMinutes(placeDefault.minutes);
    }
  }
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
        <TravelModePicker
          name="Travel time"
          mode={mode}
          minutes={minutes}
          onChange={(m, min) => {
            setChosen(true);
            setMode(m);
            setMinutes(min);
          }}
        />
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
