"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";

import type { ApiClient } from "@/lib/api/client";
import {
  MIN_QUERY_LENGTH,
  comboboxReducer,
  initialComboboxState,
  isOpen,
  normalizeQuery,
  type ComboboxState,
  type NavigationKey,
} from "@/lib/suggest/combobox";

export const SUGGEST_DEBOUNCE_MS = 250;
export const SUGGEST_LIMIT = 5;

export interface AddressSuggestions {
  state: ComboboxState;
  open: boolean;
  /** Call from the input's change handler only; programmatic value changes must not call it. */
  handleInput: (text: string) => void;
  navigate: (key: NavigationKey) => void;
  /** Hides the list; a lookup still in flight keeps the closed list current. */
  dismiss: () => void;
  /** Forgets everything and abandons pending lookups, for programmatic fills. */
  reset: () => void;
}

/**
 * Suggestions are best effort. Every failure (offline, 503, timeout) just
 * leaves the list empty: the user can always press Enter to search the text
 * as typed.
 */
export function useAddressSuggestions(
  client: Pick<ApiClient, "suggestAddresses"> | null,
  { debounceMs = SUGGEST_DEBOUNCE_MS, limit = SUGGEST_LIMIT } = {},
): AddressSuggestions {
  const [state, dispatch] = useReducer(comboboxReducer, initialComboboxState);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const controller = useRef<AbortController | null>(null);
  const lastQuery = useRef("");

  const cancelPending = useCallback(() => {
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = null;
    controller.current?.abort();
    controller.current = null;
  }, []);

  useEffect(() => cancelPending, [cancelPending]);

  const handleInput = useCallback(
    (text: string) => {
      const query = normalizeQuery(text);
      dispatch({ type: "typed", text });
      if (query === lastQuery.current) return;
      lastQuery.current = query;

      cancelPending();
      if (!client || query.length < MIN_QUERY_LENGTH) return;

      timer.current = setTimeout(() => {
        timer.current = null;
        const request = new AbortController();
        controller.current = request;
        client
          .suggestAddresses(query, { limit, signal: request.signal })
          .then((suggestions) => {
            if (!request.signal.aborted) {
              dispatch({ type: "received", query, suggestions });
            }
          })
          .catch(() => {
            if (!request.signal.aborted) dispatch({ type: "failed", query });
          });
      }, debounceMs);
    },
    [cancelPending, client, debounceMs, limit],
  );

  const dismiss = useCallback(() => dispatch({ type: "dismiss" }), []);

  const reset = useCallback(() => {
    cancelPending();
    lastQuery.current = "";
    dispatch({ type: "reset" });
  }, [cancelPending]);

  const navigate = useCallback(
    (key: NavigationKey) => dispatch({ type: "navigate", key }),
    [],
  );

  return { state, open: isOpen(state), handleInput, navigate, dismiss, reset };
}
