"use client";

import Link from "next/link";
import { useState } from "react";

import { APP_PATH } from "@/lib/site";

import styles from "./HomePage.module.css";
import { HomeSearch } from "./HomeSearch";

/** Where "Ask Benri" goes: the chat opens, the typed text is only handed over. */
export function askHref(text: string): string {
  const trimmed = text.trim();
  return trimmed
    ? `${APP_PATH}?${new URLSearchParams({ chat: "1", ask: trimmed })}`
    : `${APP_PATH}?chat=1`;
}

/** The hero search plus its two follow-on actions, which share the typed text. */
export function HeroSearch() {
  const [text, setText] = useState("");
  return (
    <>
      <HomeSearch onValueChange={setText} />
      <div className={styles.actions}>
        <Link className={styles.explore} href={APP_PATH} prefetch={false}>
          <svg
            className={styles.exploreIcon}
            viewBox="0 0 24 24"
            aria-hidden="true"
            focusable="false"
          >
            <path d="M9 4 3 6.5v13.5l6-2.5 6 2.5 6-2.5V4l-6 2.5zM9 4v13.5M15 6.5V20" />
          </svg>
          Explore the map
        </Link>
        <Link className={styles.explore} href={askHref(text)} prefetch={false}>
          <svg
            className={styles.exploreIcon}
            viewBox="0 0 24 24"
            aria-hidden="true"
            focusable="false"
          >
            <path d="M4 5h16v11H9l-5 4z" />
          </svg>
          Ask Benri
        </Link>
      </div>
    </>
  );
}
