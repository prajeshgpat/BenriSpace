"use client";

import { useState } from "react";

import styles from "./ShowMore.module.css";

/** Rows shown before the "Show N more" button. */
export const INITIAL_ROWS = 3;

/** The first `limit` items, with the rest behind a toggle. */
export function useShowMore<T>(items: readonly T[], limit = INITIAL_ROWS) {
  const [open, setOpen] = useState(false);
  const hidden = Math.max(0, items.length - limit);
  return {
    visible: open ? items : items.slice(0, limit),
    hidden,
    open,
    toggle: () => setOpen((value) => !value),
  };
}

interface ShowMoreButtonProps {
  hidden: number;
  open: boolean;
  onToggle: () => void;
  /** Id of the list the button reveals. */
  controls?: string;
}

/** Renders nothing when no rows are hidden. */
export function ShowMoreButton({ hidden, open, onToggle, controls }: ShowMoreButtonProps) {
  if (hidden === 0) return null;
  return (
    <button
      type="button"
      className={styles.button}
      aria-expanded={open}
      aria-controls={controls}
      onClick={onToggle}
    >
      {open ? "Show fewer" : `Show ${hidden} more`}
      <svg
        className={styles.chevron}
        viewBox="0 0 24 24"
        aria-hidden="true"
        focusable="false"
      >
        <path d="M6 9l6 6 6-6" />
      </svg>
    </button>
  );
}
