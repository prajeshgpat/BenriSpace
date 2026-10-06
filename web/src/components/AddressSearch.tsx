"use client";

import {
  useEffect,
  useId,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type Ref,
} from "react";

import { useAddressSuggestions } from "@/hooks/useAddressSuggestions";
import {
  ADDRESS_MAX_LENGTH,
  ADDRESS_PARAM,
  validateAddress,
} from "@/lib/address";
import type { ApiClient } from "@/lib/api/client";
import type { Suggestion } from "@/lib/api/types";
import { APP_PATH } from "@/lib/site";
import { describeCount, optionId } from "@/lib/suggest/combobox";

import type { ReactNode } from "react";

import styles from "./AddressSearch.module.css";

interface AddressSearchProps {
  initialValue?: string;
  initialError?: string | null;
  /**
   * Called with a validated, normalised address. When omitted the form falls
   * back to a native GET submission to the same URL shape.
   */
  onSearch?: (address: string) => void;
  /**
   * Enables autocomplete. A chosen suggestion already carries coordinates, so
   * it bypasses geocoding.
   */
  onSelectSuggestion?: (suggestion: Suggestion) => void;
  suggestClient?: Pick<ApiClient, "suggestAddresses">;
  /** Shown inside the box on its right edge, e.g. a locate button. */
  endAdornment?: ReactNode;
  /** Every keystroke, so a parent can use text that was never submitted. */
  onTextChange?: (text: string) => void;
  /** Accessible name of the field; defaults to "Address". */
  label?: string;
  placeholder?: string;
  /** Text of the submit button; defaults to "Get score". */
  submitLabel?: string;
  /**
   * A smaller single-row field with no submit button (Enter still submits)
   * and a clear button; autocomplete works as usual.
   */
  compact?: boolean;
  /** Called after the clear button empties the field (compact only). */
  onClear?: () => void;
  /** Receives the input element, e.g. to move focus to it. */
  inputRef?: Ref<HTMLInputElement>;
}

export function AddressSearch({
  initialValue = "",
  initialError = null,
  onSearch,
  onSelectSuggestion,
  suggestClient,
  endAdornment,
  onTextChange,
  label = "Address",
  placeholder = "Enter an address",
  submitLabel = "Get score",
  compact = false,
  onClear,
  inputRef: externalInputRef,
}: AddressSearchProps) {
  const id = useId();
  const inputId = `${id}-input`;
  const errorId = `${id}-error`;
  const listboxId = `${id}-listbox`;

  const inputRef = useRef<HTMLInputElement | null>(null);
  const setInputRef = (element: HTMLInputElement | null) => {
    inputRef.current = element;
    if (typeof externalInputRef === "function") externalInputRef(element);
    else if (externalInputRef) externalInputRef.current = element;
  };
  const [value, setValue] = useState(initialValue);
  const [error, setError] = useState<string | null>(initialError);

  const autocomplete = Boolean(onSelectSuggestion && suggestClient);
  const suggestions = useAddressSuggestions(autocomplete ? suggestClient! : null);
  const { state, open } = suggestions;
  const { reset } = suggestions;
  const activeIndex = open ? state.activeIndex : -1;

  // The URL owns the searched address. When it changes underneath the form
  // (back/forward, an example link) resync during render rather than
  // remounting, which would drop focus out of the field on every search.
  const [syncedValue, setSyncedValue] = useState(initialValue);
  if (syncedValue !== initialValue) {
    setSyncedValue(initialValue);
    setValue(initialValue);
    setError(initialError);
  }

  // A value that arrives from outside the field is never a reason to look up
  // suggestions, and any lookup still pending is for text that is gone.
  useEffect(() => reset(), [initialValue, reset]);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    if (!onSearch) return;
    event.preventDefault();

    const result = validateAddress(value);
    if (!result.ok) {
      setError(result.message);
      inputRef.current?.focus();
      return;
    }
    setError(null);
    reset();
    onSearch(result.value);
  }

  function clear() {
    setValue("");
    setError(null);
    reset();
    onTextChange?.("");
    onClear?.();
    inputRef.current?.focus();
  }

  function select(suggestion: Suggestion) {
    setValue(suggestion.label);
    setError(null);
    reset();
    onSelectSuggestion?.(suggestion);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (!autocomplete || event.nativeEvent.isComposing) return;

    switch (event.key) {
      case "ArrowDown":
      case "ArrowUp":
        if (state.suggestions.length === 0) return;
        event.preventDefault();
        suggestions.navigate(event.key);
        break;
      case "Home":
      case "End":
        if (!open) return;
        event.preventDefault();
        suggestions.navigate(event.key);
        break;
      case "Enter":
        if (open && activeIndex >= 0) {
          event.preventDefault();
          select(state.suggestions[activeIndex]);
        }
        break;
      case "Escape":
        if (!open) return;
        event.preventDefault();
        suggestions.dismiss();
        break;
      case "Tab":
        suggestions.dismiss();
        break;
    }
  }

  return (
    <form
      className={compact ? `${styles.form} ${styles.compact}` : styles.form}
      role={compact ? undefined : "search"}
      action={APP_PATH}
      method="get"
      noValidate
      onSubmit={handleSubmit}
    >
      <label className="sr-only" htmlFor={inputId}>
        {label}
      </label>
      <div className={styles.row}>
        <div className={styles.field}>
          <input
            ref={setInputRef}
            id={inputId}
            className={styles.input}
            type="text"
            name={ADDRESS_PARAM}
            value={value}
            onChange={(event) => {
              setValue(event.target.value);
              onTextChange?.(event.target.value);
              if (error) setError(null);
              if (autocomplete) suggestions.handleInput(event.target.value);
            }}
            onKeyDown={handleKeyDown}
            onBlur={autocomplete ? suggestions.dismiss : undefined}
            placeholder={placeholder}
            maxLength={ADDRESS_MAX_LENGTH}
            autoComplete="off"
            autoCapitalize="words"
            spellCheck={false}
            enterKeyHint="search"
            required
            {...(autocomplete
              ? {
                  role: "combobox",
                  "aria-autocomplete": "list" as const,
                  "aria-expanded": open,
                  "aria-controls": listboxId,
                  "aria-activedescendant":
                    activeIndex >= 0 ? optionId(listboxId, activeIndex) : undefined,
                }
              : {})}
            data-adorned={endAdornment || value ? (endAdornment && value ? "2" : "1") : undefined}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? errorId : undefined}
          />
          {endAdornment || value ? (
            <div className={styles.adornment}>
              {value ? (
                <button
                  type="button"
                  className={styles.clear}
                  aria-label={`Clear ${label.toLowerCase()}`}
                  // Keep focus in the box: a mousedown blur would close the list first.
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={clear}
                >
                  <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
                    <path
                      d="M6 6l12 12M18 6L6 18"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                    />
                  </svg>
                </button>
              ) : null}
              {endAdornment}
            </div>
          ) : null}
          {autocomplete ? (
            <ul
              id={listboxId}
              className={styles.listbox}
              role="listbox"
              aria-label="Address suggestions"
              hidden={!open}
            >
              {state.suggestions.map((suggestion, index) => (
                <SuggestionOption
                  key={`${suggestion.label}:${suggestion.latitude},${suggestion.longitude}`}
                  id={optionId(listboxId, index)}
                  suggestion={suggestion}
                  active={index === activeIndex}
                  onSelect={select}
                />
              ))}
            </ul>
          ) : null}
        </div>
        {compact ? null : (
          <button className={styles.button} type="submit">
            {submitLabel}
          </button>
        )}
      </div>
      {autocomplete ? (
        <p className="sr-only" role="status">
          {open ? describeCount(state.suggestions.length) : ""}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
    </form>
  );
}

interface SuggestionOptionProps {
  id: string;
  suggestion: Suggestion;
  active: boolean;
  onSelect: (suggestion: Suggestion) => void;
}

function SuggestionOption({ id, suggestion, active, onSelect }: SuggestionOptionProps) {
  const comma = suggestion.label.indexOf(",");
  const primary = comma === -1 ? suggestion.label : suggestion.label.slice(0, comma);
  const secondary = comma === -1 ? "" : suggestion.label.slice(comma + 1).trim();

  return (
    <li
      id={id}
      className={styles.option}
      role="option"
      aria-selected={active}
      data-active={active || undefined}
      // Keeps focus in the input so a click does not blur and close the list
      // before the click registers.
      onMouseDown={(event) => event.preventDefault()}
      onClick={() => onSelect(suggestion)}
    >
      <span className={styles.optionPrimary}>{primary}</span>
      {secondary ? <span className={styles.optionSecondary}>{secondary}</span> : null}
    </li>
  );
}
