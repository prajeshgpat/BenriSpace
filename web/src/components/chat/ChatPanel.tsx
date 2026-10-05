"use client";

import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";

import type { ApiClient } from "@/lib/api/client";
import { isApiError } from "@/lib/api/errors";
import type { ChatContext, ChatResult } from "@/lib/api/types";

import { FeedbackThumbs } from "../Feedback";
import styles from "./ChatPanel.module.css";

export const CHAT_INPUT_LIMIT = 500;
export const CHAT_STORAGE_KEY = "benrispace.chat.v1";
const MAX_STORED_MESSAGES = 40;

export const STARTER_QUESTIONS = [
  "Is it good for groceries and transit?",
  "Find a quieter area near here",
  "Find a neighborhood near my work, a Trader Joe's and a Planet Fitness",
] as const;

export interface ChatMessageView {
  id: string;
  /** "note" is a client-side system line (the place changed); never sent or stored. */
  role: "user" | "assistant" | "note";
  content: string;
  results?: ChatResult[];
}

export interface ChatPanelProps {
  client: ApiClient;
  /** The place and filters the user is looking at; sent with every question. */
  context?: ChatContext;
  /** Show a found area on the map (the workspace's preview). */
  onShowOnMap: (result: ChatResult) => void;
  /** Make a found area the selected location. */
  onScoreArea: (result: ChatResult) => void;
  /** Collapse the chat back to its button (the × in the header). */
  onClose?: () => void;
  /** The selected place, for the "Now looking at" notes in the log. */
  place?: { key: string | null; label: string | null };
}

type Failure = { text: string; retryable: boolean };

function failureFor(cause: unknown): Failure {
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

function loadMessages(): ChatMessageView[] {
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

function saveMessages(messages: ChatMessageView[]) {
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

function resultFacts(result: ChatResult): string {
  const facts: string[] = [];
  if (result.score !== undefined)
    facts.push(`Score ${Math.round(result.score)}`);
  if (result.weeklyMinutes !== undefined) {
    facts.push(`${Math.round(result.weeklyMinutes)} min a week`);
  }
  return facts.join(" · ");
}

let counter = 0;
function nextId(): string {
  counter += 1;
  return `m${Date.now().toString(36)}${counter}`;
}

export function ChatPanel({
  client,
  context,
  onShowOnMap,
  onScoreArea,
  onClose,
  place,
}: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessageView[]>([]);
  const [hydrated, setHydrated] = useState(false);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  // What the server says it is doing, when streaming is on.
  const [status, setStatus] = useState<string | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const inputId = useId();
  const counterId = useId();
  const seenPlace = useRef<{ key: string | null; noteId: string | null }>({
    key: place?.key ?? null,
    noteId: null,
  });

  // sessionStorage only exists in the browser; read it after mount.
  useEffect(() => {
    setMessages(loadMessages());
    setHydrated(true);
    inputRef.current?.focus({ preventScroll: true });
    return () => abortRef.current?.abort();
  }, []);

  useEffect(() => {
    if (hydrated) saveMessages(messages.filter((m) => m.role !== "note"));
  }, [messages, hydrated]);

  // The place can change while the chat is open; say so in the log. Once the
  // street address of a clicked point arrives the same note is reworded.
  const placeKey = place?.key ?? null;
  const placeLabel = place?.label ?? null;
  useEffect(() => {
    if (!hydrated) return;
    const seen = seenPlace.current;
    if (placeKey === null || !placeLabel) {
      seen.key = placeKey;
      return;
    }
    const text = `Now looking at ${placeLabel}`;
    if (seen.key !== placeKey) {
      seen.key = placeKey;
      const id = nextId();
      seen.noteId = id;
      setMessages((current) => [
        ...current,
        { id, role: "note", content: text },
      ]);
    } else if (seen.noteId) {
      const id = seen.noteId;
      setMessages((current) =>
        current[current.length - 1]?.id === id
          ? [...current.slice(0, -1), { id, role: "note", content: text }]
          : current,
      );
    }
  }, [placeKey, placeLabel, hydrated]);

  useEffect(() => {
    const log = logRef.current;
    if (log) log.scrollTop = log.scrollHeight;
  }, [messages, pending, failure]);

  const ask = useCallback(
    async (history: ChatMessageView[]) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setPending(true);
      setStatus(null);
      setFailure(null);
      try {
        const reply = await client.chat(
          history
            .filter((m) => m.role !== "note")
            .map(({ role, content }) => ({
              role: role as "user" | "assistant",
              content,
            })),
          context,
          { signal: controller.signal, onStatus: setStatus },
        );
        if (controller.signal.aborted) return;
        setMessages((current) => [
          ...current,
          {
            id: nextId(),
            role: "assistant",
            content: reply.reply,
            ...(reply.results.length > 0 ? { results: reply.results } : {}),
          },
        ]);
      } catch (cause) {
        if (controller.signal.aborted) return;
        setFailure(failureFor(cause));
      } finally {
        if (abortRef.current === controller) {
          abortRef.current = null;
          setPending(false);
        }
      }
    },
    [client, context],
  );

  function send(text: string) {
    const content = text.trim().slice(0, CHAT_INPUT_LIMIT);
    if (content === "" || pending) return;
    const history: ChatMessageView[] = [
      ...messages,
      { id: nextId(), role: "user", content },
    ];
    setMessages(history);
    setInput("");
    void ask(history);
  }

  function retry() {
    if (pending || messages.length === 0) return;
    void ask(messages);
  }

  function newChat() {
    abortRef.current?.abort();
    abortRef.current = null;
    setPending(false);
    setFailure(null);
    setMessages([]);
    setInput("");
    inputRef.current?.focus({ preventScroll: true });
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      send(input);
    }
  }

  const empty = hydrated && !messages.some((m) => m.role !== "note");
  const nearLimit = input.length >= CHAT_INPUT_LIMIT - 100;

  return (
    <section className={styles.chat} aria-label="Ask Benri">
      <header className={styles.header}>
        <h2 className={styles.title}>Ask Benri</h2>
        <div className={styles.headerActions}>
          <button
            type="button"
            className={styles.textButton}
            onClick={newChat}
            disabled={
              !messages.some((m) => m.role !== "note") && !pending && !failure
            }
          >
            New chat
          </button>
          {onClose ? (
            <button
              type="button"
              className={styles.closeButton}
              onClick={onClose}
              aria-label="Close chat"
            >
              <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                <path d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          ) : null}
        </div>
      </header>

      <div
        ref={logRef}
        className={styles.log}
        role="log"
        aria-live="polite"
        aria-relevant="additions"
        aria-label="Conversation"
        tabIndex={0}
      >
        {empty ? (
          <div className={styles.intro}>
            <p className={styles.introText}>
              Ask about neighborhoods in the New York metro. I only use
              BenriSpace data, so I can compare scores, find places near an
              address and weigh trips to work, stores and gyms.
            </p>
            <ul className={styles.chips} aria-label="Suggested questions">
              {STARTER_QUESTIONS.map((question) => (
                <li key={question}>
                  <button
                    type="button"
                    className={styles.chip}
                    onClick={() => send(question)}
                    disabled={pending}
                  >
                    {question}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {messages.map((message) =>
          message.role === "note" ? (
            <p key={message.id} className={styles.note}>
              {message.content}
            </p>
          ) : (
            <div
              key={message.id}
              className={styles.message}
              data-role={message.role}
            >
              <p className={styles.bubble}>
                <span className="sr-only">
                  {message.role === "user" ? "You: " : "BenriSpace: "}
                </span>
                {message.content}
              </p>
              {message.results ? (
                <ul className={styles.results} aria-label="Areas found">
                  {message.results.map((result, index) => (
                    <li
                      key={`${result.latitude},${result.longitude},${index}`}
                      className={styles.card}
                    >
                      <p className={styles.cardTitle}>{result.label}</p>
                      {resultFacts(result) ? (
                        <p className={styles.cardFacts}>
                          {resultFacts(result)}
                        </p>
                      ) : null}
                      <p className={styles.cardWhy}>{result.why}</p>
                      <div className={styles.cardActions}>
                        <button
                          type="button"
                          className={styles.action}
                          onClick={() => onShowOnMap(result)}
                          aria-label={`Show ${result.label} on map`}
                        >
                          Show on map
                        </button>
                        <button
                          type="button"
                          className={styles.action}
                          onClick={() => onScoreArea(result)}
                          aria-label={`Score ${result.label}`}
                        >
                          Score this area
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              ) : null}
              {message.role === "assistant" ? (
                <FeedbackThumbs
                  client={client}
                  kind="chat"
                  target={message.content}
                />
              ) : null}
            </div>
          ),
        )}

        {pending ? (
          <div
            className={styles.typing}
            role="status"
            aria-label="BenriSpace is typing"
          >
            <span className={styles.dot} aria-hidden="true" />
            <span className={styles.dot} aria-hidden="true" />
            <span className={styles.dot} aria-hidden="true" />
            {status ? <span className={styles.status}>{status}&hellip;</span> : null}
          </div>
        ) : null}

        {failure ? (
          <div className={styles.failure} role="alert">
            <p>{failure.text}</p>
            {failure.retryable ? (
              <button type="button" className={styles.action} onClick={retry}>
                Try again
              </button>
            ) : null}
          </div>
        ) : null}
      </div>

      <form
        className={styles.form}
        onSubmit={(event) => {
          event.preventDefault();
          send(input);
        }}
      >
        <label htmlFor={inputId} className="sr-only">
          Your question
        </label>
        <textarea
          id={inputId}
          ref={inputRef}
          className={styles.input}
          rows={2}
          value={input}
          maxLength={CHAT_INPUT_LIMIT}
          placeholder="Ask about a place or a search"
          aria-describedby={nearLimit ? counterId : undefined}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={onKeyDown}
        />
        <div className={styles.formRow}>
          <span id={counterId} className={styles.counter} hidden={!nearLimit}>
            {input.length}/{CHAT_INPUT_LIMIT}
          </span>
          <button
            type="submit"
            className={styles.send}
            disabled={pending || input.trim() === ""}
          >
            Send
          </button>
        </div>
      </form>
    </section>
  );
}
