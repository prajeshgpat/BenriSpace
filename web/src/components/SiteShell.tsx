import Link from "next/link";
import type { ReactNode } from "react";

import { SITE_NAME } from "@/lib/site";

import styles from "./SiteShell.module.css";

/** The slim header shared by every page; the data credits live with the page content. */
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
          <span>{SITE_NAME}</span>
        </Link>

        <span className={styles.region}>New York metro</span>
      </header>

      <div className={styles.content}>{children}</div>
    </div>
  );
}
