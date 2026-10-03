import { useSyncExternalStore } from "react";

/** The phone layout: the complement of the 56.25rem desktop breakpoint. */
export const MOBILE_QUERY = "not all and (min-width: 56.25rem)";

/**
 * Whether a media query currently matches. False on the server and wherever
 * `matchMedia` does not exist, so the desktop markup is the default.
 */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      if (typeof window === "undefined" || !window.matchMedia) return () => {};
      const list = window.matchMedia(query);
      list.addEventListener?.("change", onChange);
      return () => list.removeEventListener?.("change", onChange);
    },
    () =>
      typeof window !== "undefined" && Boolean(window.matchMedia)
        ? window.matchMedia(query).matches
        : false,
    () => false,
  );
}

export function useIsMobile(): boolean {
  return useMediaQuery(MOBILE_QUERY);
}
