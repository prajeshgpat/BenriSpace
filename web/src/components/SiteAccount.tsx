"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { LOGIN_ITEM, SETTINGS_ITEM } from "@/lib/site";

import styles from "./SiteAccount.module.css";

/** Settings (a gear) and Login, the last two things in the header. */
export function SiteAccount() {
  const pathname = usePathname();

  return (
    <div className={styles.account}>
      <Link
        href={SETTINGS_ITEM.href}
        prefetch={false}
        className={styles.settings}
        aria-label={SETTINGS_ITEM.label}
        title={SETTINGS_ITEM.label}
        aria-current={pathname === SETTINGS_ITEM.href ? "page" : undefined}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" className={styles.icon}>
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" />
        </svg>
      </Link>
      <Link
        href={LOGIN_ITEM.href}
        prefetch={false}
        className={styles.login}
        aria-current={pathname === LOGIN_ITEM.href ? "page" : undefined}
      >
        {LOGIN_ITEM.label}
      </Link>
    </div>
  );
}
