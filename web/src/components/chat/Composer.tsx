import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  type KeyboardEvent,
  type RefObject,
} from "react";

import { CHAT_INPUT_LIMIT } from "./chatSession";
import styles from "./ChatPanel.module.css";

const NEAR_LIMIT_MARGIN = 100;

interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onStop: () => void;
  pending: boolean;
  inputRef: RefObject<HTMLTextAreaElement | null>;
}

/** Grows the textarea with its content; the CSS max-height caps it at about five rows. */
function useAutoGrow(ref: RefObject<HTMLTextAreaElement | null>, value: string) {
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    if (el.scrollHeight > 0) el.style.height = `${el.scrollHeight}px`;
  }, [ref, value]);
}

/**
 * Keeps the composer on screen when the on-screen keyboard opens: the visual
 * viewport shrinks, so bring the form back into view once it settles.
 */
function useKeyboardAvoidance(
  formRef: RefObject<HTMLFormElement | null>,
  inputRef: RefObject<HTMLTextAreaElement | null>,
) {
  useEffect(() => {
    const viewport = window.visualViewport;
    if (!viewport) return;
    const reveal = () => {
      if (document.activeElement === inputRef.current) {
        formRef.current?.scrollIntoView?.({ block: "end" });
      }
    };
    viewport.addEventListener("resize", reveal);
    return () => viewport.removeEventListener("resize", reveal);
  }, [formRef, inputRef]);
}

export function Composer({ value, onChange, onSend, onStop, pending, inputRef }: ComposerProps) {
  const inputId = useId();
  const counterId = useId();
  const formRef = useRef<HTMLFormElement>(null);
  useAutoGrow(inputRef, value);
  useKeyboardAvoidance(formRef, inputRef);
  const nearLimit = value.length >= CHAT_INPUT_LIMIT - NEAR_LIMIT_MARGIN;

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      onSend();
    }
  }

  return (
    <form
      ref={formRef}
      className={styles.form}
      onSubmit={(event) => {
        event.preventDefault();
        onSend();
      }}
    >
      <label htmlFor={inputId} className="sr-only">
        Your question
      </label>
      <div className={styles.inputRow}>
        <textarea
          id={inputId}
          ref={inputRef}
          className={styles.input}
          rows={1}
          value={value}
          maxLength={CHAT_INPUT_LIMIT}
          placeholder="Ask about a place or a search"
          enterKeyHint="send"
          aria-describedby={nearLimit ? counterId : undefined}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={onKeyDown}
        />
        {pending ? (
          <button type="button" className={styles.stop} onClick={onStop} aria-label="Stop">
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
              <rect x="7" y="7" width="10" height="10" rx="2" />
            </svg>
          </button>
        ) : (
          <button
            type="submit"
            className={styles.send}
            aria-label="Send"
            disabled={value.trim() === ""}
          >
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
              <path d="M12 19V5M5 12l7-7 7 7" />
            </svg>
          </button>
        )}
      </div>
      <span id={counterId} className={styles.counter} hidden={!nearLimit}>
        {value.length}/{CHAT_INPUT_LIMIT}
      </span>
    </form>
  );
}
