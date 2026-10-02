"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { SITE_NAME } from "@/lib/site";

import { SiteFooter } from "./SiteFooter";
import styles from "./SiteShell.module.css";

const NAV = [
  { href: "/", label: "Score an address" },
  { href: "/map", label: "Explore the map" },
] as const;

/**
 * Header, navigation and the data-attribution footer shared by every page.
 * The map page fills the viewport, so the shell pins its height there and
 * lets the page between header and footer take the rest.
 */
export function SiteShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const fill = pathname === "/map";

  return (
    <div className={styles.shell} data-fill={fill || undefined}>
      <a className="skip-link" href="#main">
        Skip to content
      </a>

      <header className={styles.header}>
        <div className={styles.headerInner}>
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
            <span className={styles.wordmark}>{SITE_NAME}</span>
          </Link>

          <nav className={styles.nav} aria-label="Main">
            {NAV.map(({ href, label }) => (
              <Link
                key={href}
                className={styles.navLink}
                href={href}
                prefetch={false}
                aria-current={pathname === href ? "page" : undefined}
              >
                {label}
              </Link>
            ))}
          </nav>

          <span className={styles.region}>New York metro</span>
        </div>
      </header>

      <div className={styles.content}>{children}</div>

      <SiteFooter />
    </div>
  );
}
