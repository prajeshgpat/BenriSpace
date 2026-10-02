"use client";

import { useCallback, useSyncExternalStore } from "react";

import {
  THEME_CHANGE_EVENT,
  THEME_STORAGE_KEY,
  oppositeTheme,
  parsePreference,
  resolveTheme,
  type ResolvedTheme,
  type ThemePreference,
} from "@/lib/theme";

const DARK_QUERY = "(prefers-color-scheme: dark)";

function readPreference(): ThemePreference {
  return parsePreference(document.documentElement.dataset.theme);
}

function systemPrefersDark(): boolean {
  return window.matchMedia(DARK_QUERY).matches;
}

function subscribe(onChange: () => void): () => void {
  const media = window.matchMedia(DARK_QUERY);
  const onStorage = (event: StorageEvent) => {
    if (event.key !== THEME_STORAGE_KEY) return;
    // Another tab changed the choice: follow it.
    applyPreference(parsePreference(event.newValue), false);
    onChange();
  };
  // Safari before 14 only has the deprecated addListener.
  if (media.addEventListener) media.addEventListener("change", onChange);
  else media.addListener(onChange);
  window.addEventListener(THEME_CHANGE_EVENT, onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    if (media.removeEventListener) media.removeEventListener("change", onChange);
    else media.removeListener(onChange);
    window.removeEventListener(THEME_CHANGE_EVENT, onChange);
    window.removeEventListener("storage", onStorage);
  };
}

function applyPreference(preference: ThemePreference, persist: boolean) {
  const root = document.documentElement;
  if (preference === "system") delete root.dataset.theme;
  else root.dataset.theme = preference;
  if (!persist) return;
  try {
    if (preference === "system") localStorage.removeItem(THEME_STORAGE_KEY);
    else localStorage.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    // Storage can be blocked; the choice then lasts for this visit only.
  }
}

export interface ThemeState {
  /** What is on screen now. */
  theme: ResolvedTheme;
  /** What the visitor chose; "system" until they pick one. */
  preference: ThemePreference;
  setPreference: (preference: ThemePreference) => void;
  toggle: () => void;
}

/**
 * The saved choice lives on <html data-theme>, so the CSS, the map and this
 * hook all read one source of truth. The server and the first client render
 * assume light; the store then corrects it without a hydration mismatch.
 */
export function useTheme(): ThemeState {
  const preference = useSyncExternalStore(
    subscribe,
    readPreference,
    (): ThemePreference => "system",
  );
  const dark = useSyncExternalStore(subscribe, systemPrefersDark, () => false);
  const theme = resolveTheme(preference, dark);

  const setPreference = useCallback((next: ThemePreference) => {
    applyPreference(next, true);
    window.dispatchEvent(new Event(THEME_CHANGE_EVENT));
  }, []);
  const toggle = useCallback(() => {
    setPreference(oppositeTheme(resolveTheme(readPreference(), systemPrefersDark())));
  }, [setPreference]);

  return { theme, preference, setPreference, toggle };
}
