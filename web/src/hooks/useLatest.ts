import { useEffect, useRef, type RefObject } from "react";

/**
 * A ref that always holds the newest value, for long-lived listeners (map
 * events, timers) that must not capture stale props or be re-registered on
 * every render.
 */
export function useLatest<T>(value: T): RefObject<T> {
  const ref = useRef(value);
  useEffect(() => {
    ref.current = value;
  });
  return ref;
}
