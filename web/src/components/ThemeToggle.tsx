"use client";

import { useTheme } from "@/hooks/useTheme";

import styles from "./ThemeToggle.module.css";

/** The lightbulb: lit in light mode, dark in dark mode. */
export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const label = theme === "dark" ? "Switch to light mode" : "Switch to dark mode";

  return (
    <button type="button" className={styles.button} onClick={toggle} aria-label={label} title={label}>
      <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" className={styles.icon} data-lit={theme === "light"}>
        <path
          className={styles.glass}
          d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.6 10.8c.6.5 1 1.2 1 2V16h5.2v-.2c0-.8.4-1.5 1-2A6 6 0 0 0 12 3Z"
        />
      </svg>
    </button>
  );
}
