import type { ReactNode } from "react";

import { SiteFooter } from "./SiteFooter";
import styles from "./InfoPage.module.css";

interface InfoPageProps {
  title: string;
  lead: string;
  children?: ReactNode;
}

/** The shared frame for the menu pages that are not the app itself. */
export function InfoPage({ title, lead, children }: InfoPageProps) {
  return (
    <>
      <main id="main" className={styles.main}>
        <h1 className={styles.title}>{title}</h1>
        <p className={styles.lead}>{lead}</p>
        {children}
      </main>
      <SiteFooter />
    </>
  );
}
