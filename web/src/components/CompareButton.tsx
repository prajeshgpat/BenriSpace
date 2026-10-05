import { MAX_COMPARE } from "@/lib/compare";

import styles from "./CompareButton.module.css";

interface CompareButtonProps {
  /** What is being pinned, for the accessible name. */
  name: string;
  pinned: boolean;
  full: boolean;
  onToggle: () => void;
}

/** Pins a place for the side-by-side view (up to four). */
export function CompareButton({ name, pinned, full, onToggle }: CompareButtonProps) {
  const blocked = full && !pinned;
  return (
    <button
      type="button"
      className={styles.button}
      aria-pressed={pinned}
      disabled={blocked}
      title={blocked ? `You can compare up to ${MAX_COMPARE} places` : undefined}
      aria-label={`${pinned ? "Remove from compare" : "Compare"}: ${name}`}
      onClick={onToggle}
    >
      {pinned ? "Added to compare" : "Compare"}
    </button>
  );
}
