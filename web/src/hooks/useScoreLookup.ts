"use client";

import { useCallback, useEffect, useState } from "react";

import type { ApiClient } from "@/lib/api/client";
import { ApiError, isApiError } from "@/lib/api/errors";
import type { Score } from "@/lib/api/types";

export type ExplanationState =
  | { status: "loading" }
  | { status: "ready"; text: string }
  | { status: "unavailable" };

export type LookupState =
  | { status: "idle" }
  | { status: "loading"; address: string }
  | {
      status: "success";
      address: string;
      score: Score;
      explanation: ExplanationState;
    }
  | { status: "error"; address: string; error: ApiError };

export interface ScoreLookup {
  state: LookupState;
  /** Re-runs the lookup for the current address. */
  retry: () => void;
}

type Settled = Extract<LookupState, { status: "success" | "error" }>;

interface Entry {
  requestKey: string;
  state: Settled;
}

function toApiError(cause: unknown): ApiError {
  return isApiError(cause)
    ? cause
    : new ApiError("server", "Unexpected error while loading the score.", {
        cause,
      });
}

export function useScoreLookup(
  address: string | null,
  client: ApiClient,
): ScoreLookup {
  const [attempt, setAttempt] = useState(0);
  const [entry, setEntry] = useState<Entry | null>(null);

  const requestKey = address === null ? null : `${attempt}:${address}`;

  useEffect(() => {
    if (address === null || requestKey === null) return;

    const controller = new AbortController();
    const { signal } = controller;
    const settle = (state: Settled) => {
      if (!signal.aborted) setEntry({ requestKey, state });
    };

    (async () => {
      let score: Score;
      try {
        score = await client.getScore(address, { signal });
      } catch (cause) {
        settle({ status: "error", address, error: toApiError(cause) });
        return;
      }
      settle({
        status: "success",
        address,
        score,
        explanation: { status: "loading" },
      });

      // The explanation is supplementary: if it fails, the score still stands.
      let explanation: ExplanationState;
      try {
        const { explanation: text } = await client.getScoreExplanation(
          score.geoEntityId,
          { signal },
        );
        explanation = text.trim()
          ? { status: "ready", text }
          : { status: "unavailable" };
      } catch {
        explanation = { status: "unavailable" };
      }
      settle({ status: "success", address, score, explanation });
    })();

    return () => controller.abort();
  }, [address, client, requestKey]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  // Deriving "loading" from a key mismatch, instead of storing it, means a
  // previous address's result can never be shown against the current one.
  let state: LookupState;
  if (address === null || requestKey === null) {
    state = { status: "idle" };
  } else if (entry?.requestKey === requestKey) {
    state = entry.state;
  } else {
    state = { status: "loading", address };
  }

  return { state, retry };
}
