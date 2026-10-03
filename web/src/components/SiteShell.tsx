import Link from "next/link";
import type { ReactNode } from "react";

import { SITE_NAME } from "@/lib/site";

import { BrandMark } from "./BrandMark";
import { MobileMenu } from "./MobileMenu";
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

      <MobileMenu />

      <header className={styles.header}>
        <Link className={styles.brand} href="/" prefetch={false}>
          <BrandMark className={styles.mark} />
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
