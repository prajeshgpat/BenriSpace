import { Suspense } from "react";

import { AddressSearch } from "@/components/AddressSearch";
import { ScoreExplorer } from "@/components/ScoreExplorer";
import { SITE_NAME } from "@/lib/site";

import styles from "./page.module.css";

export default function HomePage() {
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <div className={styles.shell}>
        <header className={styles.header}>
          <span className={styles.brand}>
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
            {SITE_NAME}
          </span>
          <span className={styles.region}>New York metro</span>
        </header>

        <main id="main" className={styles.main}>
          <div className={styles.intro}>
            <h1 className={styles.title}>How convenient is that address?</h1>
            <p className={styles.lede}>
              Enter an address in the New York metro area to see how it scores
              on groceries, transit, schools, trails and more.
            </p>
          </div>

          {/*
            useSearchParams() opts its subtree out of static prerendering, so
            the boundary keeps the rest of the page static. The fallback is the
            same search form, so the prerendered HTML already has the primary
            control in place and nothing shifts on hydration.
          */}
          <Suspense fallback={<AddressSearch />}>
            <ScoreExplorer />
          </Suspense>
        </main>

        <footer className={styles.footer}>
          <p>
            Scores are precomputed from open data, including map data ©{" "}
            <a
              href="https://www.openstreetmap.org/copyright"
              rel="noreferrer"
              target="_blank"
            >
              OpenStreetMap contributors
            </a>
            . They describe an area, not a single building.
          </p>
        </footer>
      </div>
    </>
  );
}
