"use client";

import type { ReactNode } from "react";

import type { ReachMode } from "@/lib/api/types";
import { TRAVEL_OPTIONS, travelOption } from "@/lib/travel";

import styles from "./TravelModePicker.module.css";

export interface TravelModePickerProps {
  mode: ReachMode;
  minutes: number;
  onChange: (mode: ReachMode, minutes: number) => void;
  /** Names the groups: "Travel mode for {name}". "Travel time" keeps the plain labels. */
  name: string;
  disabled?: boolean;
}

function Glyph({ children, filled = false }: { children: ReactNode; filled?: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={18}
      height={18}
      {...(filled
        ? { fill: "currentColor" }
        : {
            fill: "none",
            stroke: "currentColor",
            strokeWidth: 2,
            strokeLinecap: "round" as const,
            strokeLinejoin: "round" as const,
          })}
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

// Walk: Material "directions_walk" (Apache-2.0). Train and car after Lucide (ISC).
const ICONS: Record<ReachMode, ReactNode> = {
  walk: (
    <Glyph filled>
      <path d="M13.5 5.5c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zM9.8 8.9 7 23h2.1l1.8-8 2.1 2v6h2v-7.5l-2.1-2 .6-3C14.8 12 16.8 13 19 13v-2c-1.9 0-3.5-1-4.3-2.4l-1-1.6c-.4-.6-1-1-1.7-1-.3 0-.5.1-.8.1L6 8.3V13h2V9.6l1.8-.7" />
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

/** The icon for one travel mode (decorative: the button around it carries the name). */
export function TravelModeIcon({ mode }: { mode: ReachMode }) {
  return ICONS[mode];
}

/**
 * The mode's icon with its minutes in a small circle on the bottom right, so a closed toggle
 * still says how far the place reaches (decorative, like the icon).
 */
export function TravelBadge({ mode, minutes }: { mode: ReachMode; minutes: number }) {
  return (
    <span className={styles.badged} aria-hidden="true">
      {ICONS[mode]}
      <span className={styles.badge} data-testid="travel-badge">
        {minutes}
      </span>
    </span>
  );
}

interface MinutesStepperProps {
  mode: ReachMode;
  minutes: number;
  /** Called with the same mode and the neighbouring step. */
  onChange: (mode: ReachMode, minutes: number) => void;
  label: string;
  fewerLabel: string;
  moreLabel: string;
  disabled?: boolean;
  className?: string;
}

/** A minus / value / plus stepper over the minutes the mode allows. */
export function MinutesStepper({
  mode,
  minutes,
  onChange,
  label,
  fewerLabel,
  moreLabel,
  disabled,
  className,
}: MinutesStepperProps) {
  const current = travelOption(mode);
  const step = current.minutes.indexOf(minutes);
  return (
    <div
      className={className ? `${styles.stepper} ${className}` : styles.stepper}
      role="group"
      aria-label={label}
    >
      <button
        type="button"
        className={styles.step}
        aria-label={fewerLabel}
        disabled={disabled || step <= 0}
        onClick={() => onChange(mode, current.minutes[Math.max(step - 1, 0)])}
      >
        &minus;
      </button>
      <span className={styles.value} aria-live="polite">
        {minutes} min
      </span>
      <button
        type="button"
        className={styles.step}
        aria-label={moreLabel}
        disabled={disabled || step >= current.minutes.length - 1}
        onClick={() =>
          onChange(mode, current.minutes[Math.min(step + 1, current.minutes.length - 1)])
        }
      >
        +
      </button>
    </div>
  );
}

/** Mode icon buttons plus a minus / value / plus minutes stepper. */
export function TravelModePicker({ mode, minutes, onChange, name, disabled }: TravelModePickerProps) {
  const plain = name === "Travel time";
  const modeLabel = plain ? "Travel mode" : `Travel mode for ${name}`;
  const minutesLabel = plain ? "Minutes" : `Minutes for ${name}`;
  const fewerLabel = name === "Travel time" ? "Fewer minutes" : `Fewer minutes for ${name}`;
  const moreLabel = name === "Travel time" ? "More minutes" : `More minutes for ${name}`;

  return (
    <div className={styles.picker}>
      <div className={styles.modes} role="group" aria-label={modeLabel}>
        {TRAVEL_OPTIONS.map((o) => (
          <button
            key={o.mode}
            type="button"
            className={o.mode === mode ? styles.modeOn : styles.mode}
            aria-pressed={o.mode === mode}
            aria-label={o.label}
            title={o.label}
            disabled={disabled}
            onClick={() => onChange(o.mode, o.initial)}
          >
            {ICONS[o.mode]}
          </button>
        ))}
      </div>
      <MinutesStepper
        mode={mode}
        minutes={minutes}
        onChange={onChange}
        label={minutesLabel}
        fewerLabel={fewerLabel}
        moreLabel={moreLabel}
        disabled={disabled}
      />
    </div>
  );
}
