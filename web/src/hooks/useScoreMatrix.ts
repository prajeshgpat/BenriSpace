"use client";

import { useEffect, useState } from "react";

import type { ApiClient } from "@/lib/api/client";
import { decodeScoreMatrix, type ScoreMatrix } from "@/lib/scores/matrix";

export type ScoreMatrixState =
  | { status: "loading"; matrix: null }
  | { status: "ready"; matrix: ScoreMatrix }
  | { status: "failed"; matrix: null };

const cache = new WeakMap<object, Promise<ScoreMatrix>>();

/** One download per client for the life of the page; a failure is not cached. */
export function loadScoreMatrix(
  client: Pick<ApiClient, "getMapScores">,
): Promise<ScoreMatrix> {
  const known = cache.get(client);
  if (known) return known;
  const loading = Promise.resolve()
    .then(() => client.getMapScores())
    .then(decodeScoreMatrix);
  cache.set(client, loading);
  loading.catch(() => cache.delete(client));
  return loading;
}

/**
 * Downloads `/v1/map/scores` once and decodes it into typed arrays so the
 * browser can recolour the map and rank areas itself. While it loads, or if it
 * cannot be loaded or decoded, callers keep using the API.
 */
export function useScoreMatrix(
  client: Pick<ApiClient, "getMapScores">,
): ScoreMatrixState {
  const [state, setState] = useState<ScoreMatrixState>({
    status: "loading",
    matrix: null,
  });
  useEffect(() => {
    let cancelled = false;
    loadScoreMatrix(client).then(
      (matrix) => {
        if (!cancelled) setState({ status: "ready", matrix });
      },
      () => {
        if (!cancelled) setState({ status: "failed", matrix: null });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [client]);
  return state;
}
