"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import styles from "./AuthForm.module.css";

type Mode = "signin" | "signup";

const NOTICE =
  "Accounts aren't available yet. You can use BenriSpace without signing in.";
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

type Errors = Partial<Record<"name" | "email" | "password", string>>;

function validate(mode: Mode, data: FormData): Errors {
  const errors: Errors = {};
  const name = String(data.get("name") ?? "").trim();
  const email = String(data.get("email") ?? "").trim();
  const password = String(data.get("password") ?? "");
  if (mode === "signup" && !name) errors.name = "Enter your name.";
  if (!email) errors.email = "Enter your email address.";
  else if (!EMAIL_RE.test(email)) errors.email = "Enter a valid email address.";
  if (!password) errors.password = "Enter your password.";
  else if (mode === "signup" && password.length < 8) {
    errors.password = "Use at least 8 characters.";
  }
  return errors;
}

/** Sign-in and create-account form. UI only: nothing is sent anywhere yet. */
export function AuthForm() {
  const [mode, setMode] = useState<Mode>("signin");
  const [errors, setErrors] = useState<Errors>({});
  const [notice, setNotice] = useState(false);
  const signup = mode === "signup";

  function switchMode(next: Mode) {
    setMode(next);
    setErrors({});
    setNotice(false);
  }

  // The auth provider call plugs in here, after validation passes.
  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found = validate(mode, new FormData(event.currentTarget));
    setErrors(found);
    setNotice(Object.keys(found).length === 0);
  }

  // The Google OAuth redirect plugs in here.
  function onGoogle() {
    setErrors({});
    setNotice(true);
  }

  return (
    <div className={styles.panel}>
      <h2 className={styles.heading}>
        {signup ? "Create your account" : "Sign in"}
      </h2>
      <button type="button" className={styles.google} onClick={onGoogle}>
        <svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18">
          <path
            fill="#4285F4"
            d="M22.5 12.27c0-.8-.07-1.56-.2-2.3H12v4.35h5.9a5.05 5.05 0 0 1-2.19 3.31v2.75h3.54c2.07-1.91 3.25-4.72 3.25-8.11z"
          />
          <path
            fill="#34A853"
            d="M12 23c2.97 0 5.46-.98 7.28-2.67l-3.54-2.75c-.98.66-2.24 1.05-3.74 1.05-2.88 0-5.31-1.94-6.18-4.55H2.17v2.84A11 11 0 0 0 12 23z"
          />
          <path
            fill="#FBBC05"
            d="M5.82 14.08a6.6 6.6 0 0 1 0-4.16V7.08H2.17a11 11 0 0 0 0 9.84l3.65-2.84z"
          />
          <path
            fill="#EA4335"
            d="M12 5.37c1.62 0 3.07.56 4.21 1.65l3.15-3.15C17.45 2.09 14.97 1 12 1A11 11 0 0 0 2.17 7.08l3.65 2.84C6.69 7.31 9.12 5.37 12 5.37z"
          />
        </svg>
        Continue with Google
      </button>
      <div className={styles.divider} role="separator">
        <span>or</span>
      </div>
      <form className={styles.form} onSubmit={onSubmit} noValidate>
        {signup ? (
          <Field
            id="auth-name"
            name="name"
            label="Name"
            autoComplete="name"
            error={errors.name}
          />
        ) : null}
        <Field
          id="auth-email"
          name="email"
          label="Email"
          type="email"
          autoComplete="email"
          error={errors.email}
        />
        <Field
          id="auth-password"
          name="password"
          label="Password"
          type="password"
          autoComplete={signup ? "new-password" : "current-password"}
          error={errors.password}
          hint={signup ? "At least 8 characters." : undefined}
        />
        {!signup ? (
          <Link
            href="/login"
            className={styles.forgot}
            onClick={(e) => {
              // Password reset plugs in here.
              e.preventDefault();
              setErrors({});
              setNotice(true);
            }}
          >
            Forgot password?
          </Link>
        ) : null}
        {notice ? (
          <p role="status" className={styles.notice}>
            {NOTICE}
          </p>
        ) : null}
        <button type="submit" className={styles.submit}>
          {signup ? "Create account" : "Sign in"}
        </button>
      </form>
      <p className={styles.switch}>
        {signup ? "Already have an account? " : "New to BenriSpace? "}
        <button
          type="button"
          className={styles.linkButton}
          onClick={() => switchMode(signup ? "signin" : "signup")}
        >
          {signup ? "Sign in" : "Create account"}
        </button>
      </p>
      <p className={styles.back}>
        <Link href="/app">Continue to the app without signing in</Link>
      </p>
    </div>
  );
}

interface FieldProps {
  id: string;
  name: string;
  label: string;
  type?: string;
  autoComplete: string;
  error?: string;
  hint?: string;
}

function Field({
  id,
  name,
  label,
  type = "text",
  autoComplete,
  error,
  hint,
}: FieldProps) {
  const describedBy = [error ? `${id}-error` : null, hint ? `${id}-hint` : null]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={styles.field}>
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        name={name}
        type={type}
        autoComplete={autoComplete}
        required
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy || undefined}
      />
      {hint ? (
        <span id={`${id}-hint`} className={styles.hint}>
          {hint}
        </span>
      ) : null}
      {error ? (
        <span id={`${id}-error`} className={styles.error}>
          {error}
        </span>
      ) : null}
    </div>
  );
}
