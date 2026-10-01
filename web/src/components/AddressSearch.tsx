"use client";

import { useId, useRef, useState, type FormEvent } from "react";

import {
  ADDRESS_MAX_LENGTH,
  ADDRESS_PARAM,
  validateAddress,
} from "@/lib/address";

import styles from "./AddressSearch.module.css";

interface AddressSearchProps {
  initialValue?: string;
  initialError?: string | null;
  /**
   * Called with a validated, normalised address. When omitted the form falls
   * back to a native GET submission to the same URL shape.
   */
  onSearch?: (address: string) => void;
}

export function AddressSearch({
  initialValue = "",
  initialError = null,
  onSearch,
}: AddressSearchProps) {
  const id = useId();
  const inputId = `${id}-input`;
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;

  const inputRef = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState(initialValue);
  const [error, setError] = useState<string | null>(initialError);

  // The URL owns the searched address. When it changes underneath the form
  // (back/forward, an example link) resync during render rather than
  // remounting, which would drop focus out of the field on every search.
  const [syncedValue, setSyncedValue] = useState(initialValue);
  if (syncedValue !== initialValue) {
    setSyncedValue(initialValue);
    setValue(initialValue);
    setError(initialError);
  }

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
    onSearch(result.value);
  }

  return (
    <form
      className={styles.form}
      role="search"
      action="/"
      method="get"
      noValidate
      onSubmit={handleSubmit}
    >
      <label className={styles.label} htmlFor={inputId}>
        Address
      </label>
      <div className={styles.row}>
        <input
          ref={inputRef}
          id={inputId}
          className={styles.input}
          type="text"
          name={ADDRESS_PARAM}
          value={value}
          onChange={(event) => {
            setValue(event.target.value);
            if (error) setError(null);
          }}
          placeholder="350 5th Ave, New York, NY"
          maxLength={ADDRESS_MAX_LENGTH}
          autoComplete="off"
          autoCapitalize="words"
          spellCheck={false}
          enterKeyHint="search"
          required
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${errorId} ${hintId}` : hintId}
        />
        <button className={styles.button} type="submit">
          Get score
        </button>
      </div>
      {error ? (
        <p id={errorId} className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
      <p id={hintId} className={styles.hint}>
        Street address, neighborhood or landmark within about two hours of New
        York City.
      </p>
    </form>
  );
}
