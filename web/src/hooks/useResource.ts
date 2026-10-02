"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";

import { ApiError, isApiError } from "@/lib/api/errors";

export type ResourceStatus = "idle" | "loading" | "ready" | "error";

export interface Resource<T> {
  status: ResourceStatus;
  /** The last successful result. It stays put while the next one loads. */
  data: T | null;
  error: ApiError | null;
  retry: () => void;
}

interface State<T> {
  requestKey: string | null;
  status: "ready" | "error";
  data: T | null;
  error: ApiError | null;
}

type Action<T> =
  | { type: "ready"; requestKey: string; data: T }
  | { type: "error"; requestKey: string; error: ApiError }
  | { type: "clear" };

function reducer<T>(state: State<T>, action: Action<T>): State<T> {
  switch (action.type) {
    case "ready":
      return {
        requestKey: action.requestKey,
        status: "ready",
        data: action.data,
        error: null,
      };
    case "error":
      // The previous data stays on screen behind the error.
      return {
        ...state,
        requestKey: action.requestKey,
        status: "error",
        error: action.error,
      };
    case "clear":
      return { requestKey: null, status: "ready", data: null, error: null };
  }
}

function toApiError(cause: unknown): ApiError {
  return isApiError(cause)
    ? cause
    : new ApiError("server", "Unexpected error while loading.", { cause });
}

/**
 * Loads whatever `fetcher` returns whenever `key` changes, aborting the
 * request it replaces. `null` means there is nothing to load. Previous data
 * is kept while a new request is in flight so a map never blanks between
 * pans or toggles.
 */
export function useResource<T>(
  key: string | null,
  fetcher: (signal: AbortSignal) => Promise<T>,
): Resource<T> {
  const [attempt, bump] = useReducer((n: number) => n + 1, 0);
  const [state, dispatch] = useReducer(reducer<T>, {
    requestKey: null,
    status: "ready",
    data: null,
    error: null,
  });
  const latestFetcher = useRef(fetcher);
  useEffect(() => {
    latestFetcher.current = fetcher;
  });

  const requestKey = key === null ? null : `${attempt}:${key}`;

  useEffect(() => {
    if (requestKey === null) {
      dispatch({ type: "clear" });
      return;
    }
    const controller = new AbortController();
    const { signal } = controller;
    latestFetcher.current(signal).then(
      (data) => {
        if (!signal.aborted) dispatch({ type: "ready", requestKey, data });
      },
      (cause: unknown) => {
        if (!signal.aborted) {
          dispatch({ type: "error", requestKey, error: toApiError(cause) });
        }
      },
    );
    return () => controller.abort();
  }, [requestKey]);

  const retry = useCallback(() => bump(), []);

  if (requestKey === null) {
    return { status: "idle", data: null, error: null, retry };
  }
  if (state.requestKey === requestKey) {
    return {
      status: state.status,
      data: state.data,
      error: state.error,
      retry,
    };
  }
  return { status: "loading", data: state.data, error: null, retry };
}
