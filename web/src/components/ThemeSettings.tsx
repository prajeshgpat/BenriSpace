"use client";

import { useTheme } from "@/hooks/useTheme";
import type { ThemePreference } from "@/lib/theme";

import styles from "./InfoPage.module.css";

const CHOICES: ReadonlyArray<{ value: ThemePreference; label: string }> = [
  { value: "system", label: "Match my device" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

export function ThemeSettings() {
  const { preference, setPreference } = useTheme();

  return (
    <section className={styles.card}>
      <h2 id="theme-heading">Appearance</h2>
      <fieldset className={styles.choices} aria-labelledby="theme-heading">
        {CHOICES.map(({ value, label }) => (
          <label key={value} className={styles.choice}>
            <input
              type="radio"
              name="theme"
              value={value}
              checked={preference === value}
              onChange={() => setPreference(value)}
            />
            {label}
          </label>
        ))}
      </fieldset>
    </section>
  );
}
