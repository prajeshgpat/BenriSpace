"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import type { ApiClient } from "@/lib/api/client";
import type { ChatContext, ChatPlan, ChatResult } from "@/lib/api/types";

import { FeedbackThumbs } from "../Feedback";
import { Composer } from "./Composer";
import { ResultCard } from "./ResultCard";
import {
  CHAT_INPUT_LIMIT,
  CHAT_STORAGE_KEY,
  failureFor,
  loadMessages,
  nextId,
  saveMessages,
  type ChatMessageView,
  type Failure,
} from "./chatSession";
import { starterQuestions } from "./starterQuestions";
import styles from "./ChatPanel.module.css";

export { CHAT_INPUT_LIMIT, CHAT_STORAGE_KEY };
export type { ChatMessageView };

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
  /** Called once per reply that carries a plan (the main address and points of interest). */
  onPlan?: (plan: ChatPlan) => void;
  /** The selected place, for the "Now looking at" notes in the log. */
  place?: { key: string | null; label: string | null };
}

const MAX_SUGGESTIONS = 3;

export function ChatPanel({
  client,
  context,
  onShowOnMap,
  onScoreArea,
  onClose,
  onPlan,
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
  const onPlanRef = useRef(onPlan);
  onPlanRef.current = onPlan;
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

  // A new reply scrolls to ITS START, so the answer and its top results show first (jumping
  // to the bottom hid them behind the last result card, worst on a phone). While a question
  // is being sent or answered, or after an error, the log follows the bottom.
  useEffect(() => {
    const log = logRef.current;
    if (!log) return;
    const replies = log.querySelectorAll<HTMLElement>('[data-role="assistant"]');
    const last = messages[messages.length - 1];
    const reply = replies[replies.length - 1];
    if (!pending && !failure && last?.role === "assistant" && reply) {
      const offset = reply.getBoundingClientRect().top - log.getBoundingClientRect().top;
      log.scrollTop += offset - 8;
      // The page (or the phone's bottom sheet) may also have scrolled, e.g. to keep the input
      // in view: after that settles, bring the reply's first line on screen if it is not.
      const frame = requestAnimationFrame(() => {
        const top = reply.getBoundingClientRect().top;
        if (top < 0 || top > window.innerHeight * 0.6) {
          reply.scrollIntoView?.({ block: "start" });
        }
      });
      return () => cancelAnimationFrame(frame);
    }
    log.scrollTop = log.scrollHeight;
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
        if (reply.plan) onPlanRef.current?.(reply.plan);
        const suggestions = (reply.suggestions ?? []).slice(0, MAX_SUGGESTIONS);
        setMessages((current) => [
          ...current,
          {
            id: nextId(),
            role: "assistant",
            content: reply.reply,
            ...(reply.results.length > 0 ? { results: reply.results } : {}),
            ...(suggestions.length > 0 ? { suggestions } : {}),
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

  // Stop: abort the request but keep the question in the log, with a note.
  function stop() {
    if (!abortRef.current) return;
    abortRef.current.abort();
    abortRef.current = null;
    setPending(false);
    setStatus(null);
    setMessages((current) => [
      ...current,
      { id: nextId(), role: "note", content: "Stopped. Ask again whenever you like." },
    ]);
    inputRef.current?.focus({ preventScroll: true });
  }

  const empty = hydrated && !messages.some((m) => m.role !== "note");
  const hasPlace = Boolean(context?.address) || context?.latitude !== undefined;
  const hasTrip = context?.trip !== undefined;
  const starters = useMemo(
    () => starterQuestions(context?.factors, hasPlace, hasTrip),
    [context?.factors, hasPlace, hasTrip],
  );
  const lastMessage = messages[messages.length - 1];
  const followUps =
    !pending && !failure && lastMessage?.role === "assistant"
      ? (lastMessage.suggestions ?? [])
      : [];

  return (
    <div className={styles.enter}>
      <div className={styles.enterInner}>
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
                  Find areas by commute and everyday stops, compare scores, or
                  have a place explained. I only use BenriSpace data, so I
                  can weigh your daily trip to work, groceries, gyms, cafes and
                  more.
                </p>
                <Chips
                  label="Suggested questions"
                  questions={starters}
                  onPick={send}
                  disabled={pending}
                />
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
                  <div className={styles.bubble}>
                    {message.content
                      .split(/\n{2,}/)
                      .filter((part) => part.trim() !== "")
                      .map((part, index) => (
                        <p key={index} className={styles.paragraph}>
                          {index === 0 ? (
                            <span className="sr-only">
                              {message.role === "user" ? "You: " : "BenriSpace: "}
                            </span>
                          ) : null}
                          {part.trim()}
                        </p>
                      ))}
                  </div>
                  {message.results ? (
                    <ul className={styles.results} aria-label="Areas found">
                      {message.results.map((result, index) => (
                        <ResultCard
                          key={`${result.latitude},${result.longitude},${index}`}
                          result={result}
                          rank={index + 1}
                          onShowOnMap={onShowOnMap}
                          onScoreArea={onScoreArea}
                        />
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

            {followUps.length > 0 ? (
              <Chips label="Follow-up questions" questions={followUps} onPick={send} />
            ) : null}

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

          <Composer
            value={input}
            onChange={setInput}
            onSend={() => send(input)}
            onStop={stop}
            pending={pending}
            inputRef={inputRef}
          />
        </section>
      </div>
    </div>
  );
}

function Chips({
  label,
  questions,
  onPick,
  disabled = false,
}: {
  label: string;
  questions: readonly string[];
  onPick: (question: string) => void;
  disabled?: boolean;
}) {
  return (
    <ul className={styles.chips} aria-label={label}>
      {questions.map((question) => (
        <li key={question}>
          <button
            type="button"
            className={styles.chip}
            onClick={() => onPick(question)}
            disabled={disabled}
          >
            {question}
          </button>
        </li>
      ))}
    </ul>
  );
}
