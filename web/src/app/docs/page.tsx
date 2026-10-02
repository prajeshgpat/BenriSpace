import type { Metadata } from "next";

import { InfoPage } from "@/components/InfoPage";
import styles from "@/components/InfoPage.module.css";

export const metadata: Metadata = { title: "API · BenriSpace" };

const EXAMPLE =
  'curl "https://api.benrispace.com/v1/score?address=Grand+Central+Terminal,+New+York"';

export default function ApiPage() {
  return (
    <InfoPage
      title="API"
      lead="The same scores that power the map, over a plain HTTP API. No key is needed today."
    >
      <section className={styles.card}>
        <h2>Try it</h2>
        <pre className={styles.code}>
          <code>{EXAMPLE}</code>
        </pre>
      </section>
      <section className={styles.card}>
        <h2>Documentation</h2>
        <p>
          <a href="https://api.benrispace.com/docs">Interactive reference</a>{" "}
          (try every endpoint in the browser) and the{" "}
          <a href="https://github.com/prajeshgpat/BenriSpace/blob/main/docs/api.md">
            usage guide
          </a>{" "}
          with worked examples.
        </p>
      </section>
      <section className={styles.card}>
        <h2>API keys and limits</h2>
        <span className={styles.soon}>Coming with paid plans</span>
      </section>
    </InfoPage>
  );
}
