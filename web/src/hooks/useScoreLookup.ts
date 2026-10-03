"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { targetKey, targetLabel, type ScoreTarget } from "@/lib/address";
import type { ApiClient } from "@/lib/api/client";
import { ApiError, isApiError } from "@/lib/api/errors";
import type { AreaInfo, ExplanationSource, Score } from "@/lib/api/types";

export type ExplanationState =
  | { status: "loading" }
  | { status: "ready"; text: string; explanationSource: ExplanationSource }
  | { status: "unavailable" };

export type LookupState =
  | { status: "idle" }
  | { status: "loading"; address: string }
  | {
      status: "success";
      address: string;
      score: Score;
      /** The secondary-road polygon behind the score; null for a plain grid-square score. */
      area: AreaInfo | null;
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
  target: ScoreTarget | null,
  client: ApiClient,
): ScoreLookup {
  const [attempt, setAttempt] = useState(0);
  const [entry, setEntry] = useState<Entry | null>(null);

  const address = target === null ? null : targetLabel(target);
  const requestKey = target === null ? null : `${attempt}:${targetKey(target)}`;

  // Objects are rebuilt on every render; the key is the identity that matters.
  const targetRef = useRef(target);
  useEffect(() => {
    targetRef.current = target;
  });

  useEffect(() => {
    const current = targetRef.current;
    if (current === null || requestKey === null) return;
    const address = targetLabel(current);

    const controller = new AbortController();
    const { signal } = controller;
    const settle = (state: Settled) => {
      if (!signal.aborted) setEntry({ requestKey, state });
    };

    (async () => {
      // The area is the better answer for a point, but it is an upgrade, not
      // a requirement: any failure quietly falls back to the grid square.
      if (current.kind === "coordinates" && current.precision !== "cell") {
        try {
          const result = await client.getAreaByCoordinates(
            { lat: current.lat, lon: current.lon },
            { signal },
          );
          const text = result.explanation;
          const success = (explanation: ExplanationState): Settled => ({
            status: "success",
            address,
            score: result.score,
            area: result.area,
            explanation,
          });
          settle(
            success(
              text.trim()
                ? { status: "ready", text, explanationSource: "rules" }
                : { status: "unavailable" },
            ),
          );
          // Non-blocking upgrade: the rule-based text stays up until (and
          // unless) the AI-written one arrives. Failures are silent, and an
          // aborted signal makes `settle` drop a stale response.
          client
            .getAreaExplanation(current.lat, current.lon, signal)
            .then((ai) => {
              if (ai.source === "ai" && ai.explanation.trim()) {
                settle(
                  success({
                    status: "ready",
                    text: ai.explanation,
                    explanationSource: "ai",
                  }),
                );
              }
            })
            .catch(() => {});
          return;
        } catch {
          if (signal.aborted) return;
        }
      }

      let score: Score;
      try {
        score =
          current.kind === "address"
            ? await client.getScore(current.address, { signal })
            : await client.getScoreByCoordinates(
                { lat: current.lat, lon: current.lon },
                { signal },
              );
      } catch (cause) {
        settle({ status: "error", address, error: toApiError(cause) });
        return;
      }
      settle({
        status: "success",
        address,
        score,
        area: null,
        explanation: { status: "loading" },
      });

      // The explanation is supplementary: if it fails, the score still stands.
      let explanation: ExplanationState;
      try {
        const { explanation: text, source } =
          await client.getScoreExplanation(score.geoEntityId, { signal });
        explanation = text.trim()
          ? { status: "ready", text, explanationSource: source ?? "rules" }
          : { status: "unavailable" };
      } catch {
        explanation = { status: "unavailable" };
      }
      settle({ status: "success", address, score, area: null, explanation });
    })();

    return () => controller.abort();
  }, [client, requestKey]);

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
