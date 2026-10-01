import type { ApiErrorKind } from "./errors";

export interface ErrorMessage {
  title: string;
  body: string;
  /** Whether repeating the same request could plausibly succeed. */
  retryable: boolean;
}

const MESSAGES: Record<ApiErrorKind, ErrorMessage> = {
  "not-found": {
    title: "That address is outside our coverage",
    body: "BenriSpace currently scores the New York metro area: the five boroughs, Long Island, Westchester, the Hudson Valley, northern New Jersey and Fairfield County.",
    retryable: false,
  },
  "unresolvable-address": {
    title: "We couldn't find that address",
    body: "Check the spelling, or add a city and state, for example “350 5th Ave, New York, NY”.",
    retryable: false,
  },
  "invalid-request": {
    title: "That address doesn't look right",
    body: "Enter a street address, neighborhood or landmark in the New York metro area.",
    retryable: false,
  },
  network: {
    title: "Can't reach BenriSpace right now",
    body: "The scoring service didn't respond. Check your connection and try again.",
    retryable: true,
  },
  timeout: {
    title: "That took too long",
    body: "The scoring service didn't answer in time. Try again in a moment.",
    retryable: true,
  },
  server: {
    title: "Something went wrong on our side",
    body: "The scoring service returned an error. Try again in a moment.",
    retryable: true,
  },
  "invalid-response": {
    title: "We got an answer we couldn't read",
    body: "The scoring service returned data in an unexpected format. Try again in a moment.",
    retryable: true,
  },
};

export function describeError(kind: ApiErrorKind): ErrorMessage {
  return MESSAGES[kind];
}
