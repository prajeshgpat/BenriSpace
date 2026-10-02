import Link from "next/link";
import type { ReactNode } from "react";

import { SITE_NAME } from "@/lib/site";

import { SiteAccount } from "./SiteAccount";
import { SiteNav } from "./SiteNav";
import { ThemeToggle } from "./ThemeToggle";
import styles from "./SiteShell.module.css";

/** The header shared by every page: brand, menu tabs and the theme switch. */
export function SiteShell({ children }: { children: ReactNode }) {
  return (
    <div className={styles.shell}>
      <a className="skip-link" href="#main">
        Skip to content
      </a>

      <header className={styles.header}>
        <Link className={styles.brand} href="/" prefetch={false}>
          <svg
            className={styles.mark}
            viewBox="0 0 32 32"
            aria-hidden="true"
            focusable="false"
          >
            <rect width="32" height="32" rx="8" fill="currentColor" />
            <circle
              cx="16"
              cy="16"
              r="8"
              fill="none"
              stroke="#ffffff"
              strokeWidth="3"
            />
            <circle cx="16" cy="16" r="2.5" fill="#ffffff" />
          </svg>
          <span className={styles.name}>{SITE_NAME}</span>
        </Link>

        <div className={styles.navSlot}>
          <SiteNav />
        </div>

        <div className={styles.tools}>
          <ThemeToggle />
          <SiteAccount />
        </div>
      </header>

      <div className={styles.content}>{children}</div>
    </div>
  );
}
