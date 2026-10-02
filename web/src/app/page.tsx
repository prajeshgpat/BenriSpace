import { Suspense } from "react";

import { AddressSearch } from "@/components/AddressSearch";
import { ScoreExplorer } from "@/components/ScoreExplorer";

import styles from "./page.module.css";

export default function HomePage() {
  return (
    <div className={styles.shell}>
      <main id="main" className={styles.main}>
        <div className={styles.intro}>
          <h1 className={styles.title}>How convenient is that address?</h1>
          <p className={styles.lede}>
            Enter an address in the New York metro area to see how it scores on
            groceries, transit, schools, trails and more.
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
    </div>
  );
}
