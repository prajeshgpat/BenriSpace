import { useEffect, useRef, useState } from "react";

export const PRIORITY_DEBOUNCE_MS = 400;

/**
 * Follows `value` after it has stayed the same `key` for `delayMs`. The first
 * value is returned at once. `key` is the identity: objects rebuilt on every
 * render do not restart the timer.
 */
export function useDebouncedValue<T>(
  value: T,
  key: string,
  delayMs: number = PRIORITY_DEBOUNCE_MS,
): T {
  const [settled, setSettled] = useState({ key, value });
  const latest = useRef(value);
  useEffect(() => {
    latest.current = value;
  });

  useEffect(() => {
    if (settled.key === key) return;
    const timer = setTimeout(
      () => setSettled({ key, value: latest.current }),
      delayMs,
    );
    return () => clearTimeout(timer);
  }, [key, delayMs, settled.key]);

  return settled.value;
}
