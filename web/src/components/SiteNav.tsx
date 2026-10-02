"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { NAV_ITEMS } from "@/lib/site";

import styles from "./SiteNav.module.css";

export function SiteNav() {
  const pathname = usePathname();

  return (
    <nav aria-label="Main" className={styles.nav}>
      <ul className={styles.list}>
        {NAV_ITEMS.map(({ href, label }) => (
          <li key={href}>
            <Link
              href={href}
              prefetch={false}
              className={styles.link}
              aria-current={pathname === href ? "page" : undefined}
            >
              {label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
