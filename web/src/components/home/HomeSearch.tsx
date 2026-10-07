"use client";

import { useRouter } from "next/navigation";
import {
  useId,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";

import { useAddressSuggestions } from "@/hooks/useAddressSuggestions";
import { useCurrentLocation } from "@/hooks/useCurrentLocation";
import {
  ADDRESS_MAX_LENGTH,
  ADDRESS_PARAM,
  resultHref,
  validateAddress,
} from "@/lib/address";
import { createApiClient, type ApiClient } from "@/lib/api/client";
import type { Suggestion } from "@/lib/api/types";
import { API_BASE_URL } from "@/lib/config";
import {
  OUTSIDE_COVERAGE_MESSAGE,
  YOUR_LOCATION_LABEL,
  isInCoverage,
} from "@/lib/geolocation";
import { APP_PATH } from "@/lib/site";
import { describeCount, optionId } from "@/lib/suggest/combobox";

import { LocateButton } from "../LocateButton";

import styles from "./HomeSearch.module.css";

const defaultClient = createApiClient({ baseUrl: API_BASE_URL });

interface HomeSearchProps {
  suggestClient?: Pick<ApiClient, "suggestAddresses">;
  /** Reports the typed text so the hero can offer it to the chat. */
  onValueChange?: (value: string) => void;
}

/**
 * The hero search. Without JavaScript it is a plain GET form to the app; with
 * it, suggestions appear and a chosen one opens the app on its exact point.
 */
export function HomeSearch({
  suggestClient = defaultClient,
  onValueChange,
}: HomeSearchProps) {
  const router = useRouter();
  const id = useId();
  const listboxId = `${id}-listbox`;
  const inputRef = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);

  const suggestions = useAddressSuggestions(suggestClient);
  const { state, open } = suggestions;
  const activeIndex = open ? state.activeIndex : -1;

  const locator = useCurrentLocation(async (point) => {
    if (!isInCoverage(point)) return OUTSIDE_COVERAGE_MESSAGE;
    suggestions.reset();
    router.push(resultHref(YOUR_LOCATION_LABEL, point));
    return null;
  });
  const locating = locator.state.status === "locating";
  const locateNoteId = `${id}-locate-note`;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const result = validateAddress(value);
    if (!result.ok) {
      setError(result.message);
      inputRef.current?.focus();
      return;
    }
    suggestions.reset();
    router.push(resultHref(result.value));
  }

  function select(suggestion: Suggestion) {
    setValue(suggestion.label);
    onValueChange?.(suggestion.label);
    suggestions.reset();
    router.push(
      resultHref(suggestion.label, {
        lat: suggestion.latitude,
        lon: suggestion.longitude,
      }),
    );
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.nativeEvent.isComposing) return;
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
      className={styles.search}
      role="search"
      action={APP_PATH}
      method="get"
      onSubmit={handleSubmit}
    >
      <div className={styles.row}>
        <div className={styles.field}>
          <input
            ref={inputRef}
            className={styles.input}
            type="text"
            name={ADDRESS_PARAM}
            value={value}
            onChange={(event) => {
              setValue(event.target.value);
              onValueChange?.(event.target.value);
              if (error) setError(null);
              suggestions.handleInput(event.target.value);
            }}
            onKeyDown={handleKeyDown}
            onBlur={suggestions.dismiss}
            required
            maxLength={ADDRESS_MAX_LENGTH}
            autoComplete="off"
            autoCapitalize="words"
            spellCheck={false}
            enterKeyHint="search"
            aria-label="Address"
            placeholder="Enter an address"
            role="combobox"
            aria-autocomplete="list"
            aria-expanded={open}
            aria-controls={listboxId}
            aria-activedescendant={
              activeIndex >= 0 ? optionId(listboxId, activeIndex) : undefined
            }
            aria-invalid={error ? true : undefined}
          />
          <ul
            id={listboxId}
            className={styles.listbox}
            role="listbox"
            aria-label="Address suggestions"
            hidden={!open}
          >
            {state.suggestions.map((suggestion, index) => {
              const comma = suggestion.label.indexOf(",");
              const primary =
                comma === -1
                  ? suggestion.label
                  : suggestion.label.slice(0, comma);
              const secondary =
                comma === -1 ? "" : suggestion.label.slice(comma + 1).trim();
              return (
                <li
                  key={`${suggestion.label}:${suggestion.latitude},${suggestion.longitude}`}
                  id={optionId(listboxId, index)}
                  className={styles.option}
                  role="option"
                  aria-selected={index === activeIndex}
                  data-active={index === activeIndex || undefined}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => select(suggestion)}
                >
                  <span className={styles.optionPrimary}>{primary}</span>
                  {secondary ? (
                    <span className={styles.optionSecondary}>{secondary}</span>
                  ) : null}
                </li>
              );
            })}
          </ul>
          <div className={styles.locate}>
            <LocateButton
              variant="field"
              locating={locating}
              disabled={locator.unsupported !== null}
              describedBy={locator.unsupported ? locateNoteId : undefined}
              onClick={locator.locate}
            />
          </div>
        </div>
        <button className={styles.submit} type="submit">
          Score
        </button>
      </div>
      {locator.unsupported ? (
        <p id={locateNoteId} className={styles.note}>
          {locator.unsupported}
        </p>
      ) : null}
      <div
        aria-live="assertive"
        aria-atomic="true"
        className={styles.liveRegion}
      >
        {locator.state.status === "error" ? (
          <p className={styles.error}>{locator.state.message}</p>
        ) : null}
      </div>
      <p className="sr-only" role="status">
        {open ? describeCount(state.suggestions.length) : ""}
      </p>
      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
    </form>
  );
}
