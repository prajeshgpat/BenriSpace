"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { targetKey, targetLabel, type ScoreTarget } from "@/lib/address";
import type { ApiClient } from "@/lib/api/client";
import { ApiError, isApiError } from "@/lib/api/errors";
import type {
  AreaInfo,
  ExplanationSource,
  PriorityQuery,
  Score,
} from "@/lib/api/types";
import { hasNoFactors, priorityKey } from "@/lib/map/selection";

import { useDebouncedValue } from "./useDebouncedValue";

export type ExplanationState =
  | { status: "loading" }
  | {
      status: "ready";
      text: string;
      explanationSource: ExplanationSource;
      /** A new selection's text is loading; this is the previous one. */
      updating?: boolean;
    }
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
      /** The area's id, which keys the static area-score file. */
      areaId?: number | null;
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

/** What the explanation request last produced; `null` result means "keep the base text". */
interface Written {
  requestKey: string;
  priorityKey: string;
  result: ExplanationState | null;
}

const ALL: PriorityQuery = {};

export function useScoreLookup(
  target: ScoreTarget | null,
  client: ApiClient,
  priorities: PriorityQuery = ALL,
): ScoreLookup {
  const [attempt, setAttempt] = useState(0);
  const [entry, setEntry] = useState<Entry | null>(null);
  const [written, setWritten] = useState<Written | null>(null);

  const liveKey = priorityKey(priorities);
  // Several toggles in a row make one request, not one each.
  const settledPriorities = useDebouncedValue(priorities, liveKey);
  const settledKey = priorityKey(settledPriorities);

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
      if (current.kind === "coordinates") {
        try {
          const result = await client.getAreaByCoordinates(
            { lat: current.lat, lon: current.lon },
            { signal },
          );
          const text = result.explanation;
          settle({
            status: "success",
            address,
            score: result.score,
            area: result.area,
            areaId: result.areaId,
            explanation: text.trim()
              ? { status: "ready", text, explanationSource: "rules" }
              : { status: "unavailable" },
          });
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
    })();

    return () => controller.abort();
  }, [client, requestKey]);

  // The written explanation (AI, or the rules text for the selected factors)
  // is its own request so a new selection can refresh it without re-scoring.
  const base =
    entry?.requestKey === requestKey && entry.state.status === "success"
      ? entry.state
      : null;
  const baseRef = useRef(base);
  useEffect(() => {
    baseRef.current = base;
  });
  const writeKey = base ? requestKey : null;
  useEffect(() => {
    const current = targetRef.current;
    const settled = baseRef.current;
    if (writeKey === null || current === null || settled === null) return;
    if (hasNoFactors(settledPriorities)) return;

    const controller = new AbortController();
    const { signal } = controller;
    const query = {
      factors: settledPriorities.factors,
      weights: settledPriorities.weights,
      signal,
    };
    const fromArea = settled.area !== null && current.kind === "coordinates";
    const customised = settledPriorities.factors !== undefined || settledPriorities.weights !== undefined;
    const done = (result: ExplanationState | null) => {
      if (!signal.aborted) {
        setWritten({ requestKey: writeKey, priorityKey: settledKey, result });
      }
    };

    if (fromArea) {
      // Non-blocking upgrade: the rule-based text stays up until (and unless)
      // a better one arrives. Failures are silent.
      client
        .getAreaExplanation(current.lat, current.lon, query)
        .then((ai) => {
          // Rules text is only worth swapping in when it speaks to the
          // user's priorities; otherwise it is what `/area` already gave.
          const useIt = ai.explanation.trim() && (ai.source === "ai" || customised);
          done(
            useIt
              ? { status: "ready", text: ai.explanation, explanationSource: ai.source }
              : null,
          );
        })
        .catch(() => done(null));
    } else {
      // The explanation is supplementary: if it fails, the score still stands.
      client
        .getScoreExplanation(settled.score.geoEntityId, query)
        .then(({ explanation: text, source }) =>
          done(
            text.trim()
              ? { status: "ready", text, explanationSource: source ?? "rules" }
              : { status: "unavailable" },
          ),
        )
        .catch(() => done({ status: "unavailable" }));
    }
    return () => controller.abort();
    // `settledPriorities` is represented by `settledKey`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, writeKey, settledKey]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  // Deriving "loading" from a key mismatch, instead of storing it, means a
  // previous address's result can never be shown against the current one.
  let state: LookupState;
  if (address === null || requestKey === null) {
    state = { status: "idle" };
  } else if (entry?.requestKey === requestKey) {
    state = entry.state;
    if (state.status === "success" && written?.requestKey === requestKey && written.result) {
      const shown = written.result;
      // The previous text stays up, flagged, while the new selection's loads.
      const updating =
        shown.status === "ready" &&
        !hasNoFactors(priorities) &&
        written.priorityKey !== liveKey;
      state = {
        ...state,
        explanation: updating ? { ...shown, updating: true } : shown,
      };
    }
  } else {
    state = { status: "loading", address };
  }

  return { state, retry };
}
