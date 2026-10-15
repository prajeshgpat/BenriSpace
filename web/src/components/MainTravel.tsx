"use client";

import { useEffect, useId, useRef, useState } from "react";

import type { ReachMode } from "@/lib/api/types";
import { TRAVEL_OPTIONS, travelOption } from "@/lib/travel";

import styles from "./MainTravel.module.css";
import { MinutesStepper, TravelBadge, TravelModeIcon } from "./TravelModePicker";

export interface MainTravelProps {
  mode: ReachMode;
  minutes: number;
  onChange: (mode: ReachMode, minutes: number) => void;
  /** Whether the searched place's travel boundary is drawn on the map. */
  showOnMap: boolean;
  onShowOnMap: (on: boolean) => void;
}

/**
 * The searched place's travel mode and minutes, inside the search box on its left edge like a
 * point of interest's: the mode icon with its minutes, and a chevron that opens the modes, a
 * minutes stepper and the "Show on map" switch for the travel boundary.
 */
export function MainTravel({ mode, minutes, onChange, showOnMap, onShowOnMap }: MainTravelProps) {
  const panelId = useId();
  const showId = useId();
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const toggle = useRef<HTMLButtonElement>(null);
  const current = travelOption(mode);

  // A press anywhere else closes it; Escape closes it and returns to the toggle.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (event.target instanceof Node && root.current?.contains(event.target)) return;
      setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      toggle.current?.focus();
    };
    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div ref={root} className={styles.root} data-open={open || undefined}>
      <button
        ref={toggle}
        type="button"
        className={styles.toggle}
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={`Travel time: ${current.label}, ${minutes} minutes`}
        onClick={() => setOpen((value) => !value)}
      >
        <span className={styles.icon}>
          <TravelBadge mode={mode} minutes={minutes} />
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
        <div id={panelId} className={styles.panel}>
          <div className={styles.modes} role="group" aria-label="Travel mode">
            {TRAVEL_OPTIONS.map((o) => (
              <button
                key={o.mode}
                type="button"
                className={styles.mode}
                aria-pressed={o.mode === mode}
                aria-label={o.label}
                title={o.label}
                onClick={() => onChange(o.mode, o.initial)}
              >
                <TravelModeIcon mode={o.mode} />
              </button>
            ))}
          </div>
          <MinutesStepper
            mode={mode}
            minutes={minutes}
            onChange={onChange}
            label="Minutes"
            fewerLabel="Fewer minutes"
            moreLabel="More minutes"
          />
          <div className={styles.show}>
            <span id={showId}>Show on map</span>
            <button
              type="button"
              role="switch"
              className={styles.switch}
              aria-checked={showOnMap}
              aria-labelledby={showId}
              onClick={() => onShowOnMap(!showOnMap)}
            >
              <span className={styles.thumb} aria-hidden="true" />
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
