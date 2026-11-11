import { isApiError } from "@/lib/api/errors";
import type { ChatResult } from "@/lib/api/types";

export const CHAT_INPUT_LIMIT = 500;
export const CHAT_STORAGE_KEY = "benrispace.chat.v1";
const MAX_STORED_MESSAGES = 40;

export interface ChatMessageView {
  id: string;
  /** "note" is a client-side system line (the place changed); never sent or stored. */
  role: "user" | "assistant" | "note";
  content: string;
  results?: ChatResult[];
  /** Follow-up questions the server suggested; shown under the latest reply only. */
  suggestions?: string[];
}

export type Failure = { text: string; retryable: boolean };

export function failureFor(cause: unknown): Failure {
  if (isApiError(cause)) {
    if (cause.kind === "rate-limited") {
      return {
        text: "You’ve used today’s 15 chat questions. Come back tomorrow; the map and scores still work.",
        retryable: false,
      };
    }
    if (cause.kind === "network" || cause.kind === "timeout") {
      return {
        text: "Couldn’t reach BenriSpace. Check your connection and try again.",
        retryable: true,
      };
    }
    if (cause.status === 503 || cause.kind === "server") {
      return {
        text: "Chat is unavailable right now. Please try again later.",
        retryable: true,
      };
    }
    if (cause.kind === "invalid-request") {
      return { text: cause.message, retryable: false };
    }
  }
  return {
    text: "Something went wrong with that question. Please try again.",
    retryable: true,
  };
}

function isStoredMessage(value: unknown): value is ChatMessageView {
  if (typeof value !== "object" || value === null) return false;
  const m = value as Record<string, unknown>;
  return (
    typeof m.id === "string" &&
    (m.role === "user" || m.role === "assistant") &&
    typeof m.content === "string"
  );
}

export function loadMessages(): ChatMessageView[] {
  try {
    const raw = window.sessionStorage.getItem(CHAT_STORAGE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed)
      ? parsed.filter(isStoredMessage).slice(-MAX_STORED_MESSAGES)
      : [];
  } catch {
    return [];
  }
}

export function saveMessages(messages: ChatMessageView[]) {
  try {
    if (messages.length === 0)
      window.sessionStorage.removeItem(CHAT_STORAGE_KEY);
    else {
      window.sessionStorage.setItem(
        CHAT_STORAGE_KEY,
        JSON.stringify(messages.slice(-MAX_STORED_MESSAGES)),
      );
    }
  } catch {
    // Private mode or a full quota: the chat still works, it just is not kept.
  }
}

let counter = 0;
export function nextId(): string {
  counter += 1;
  return `m${Date.now().toString(36)}${counter}`;
}
