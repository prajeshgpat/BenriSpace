import type { Metadata } from "next";
import Link from "next/link";

import { InfoPage } from "@/components/InfoPage";
import styles from "@/components/InfoPage.module.css";
import { API_BASE_URL, MCP_URL } from "@/lib/site";

export const metadata: Metadata = { title: "Developers · BenriSpace" };

const EXAMPLE = `curl "${API_BASE_URL}/v1/score?address=Grand+Central+Terminal,+New+York"`;

export default function DevelopersPage() {
  return (
    <InfoPage
      title="Developers"
      lead="The same scores that power the map, over a plain HTTP API or as an MCP connector for AI assistants. No key is needed today."
    >
      <section id="api" className={styles.card} aria-labelledby="api-heading">
        <h2 id="api-heading">API</h2>
        <p>Score any NY, NJ or CT address, rank areas and find nearby places over HTTP.</p>
        <pre className={styles.code}>
          <code>{EXAMPLE}</code>
        </pre>
        <p>
          <a href={`${API_BASE_URL}/docs`}>Interactive reference</a> (try every endpoint in
          the browser) and the{" "}
          <a href="https://github.com/prajeshgpat/BenriSpace/blob/main/docs/api.md">
            usage guide
          </a>{" "}
          with worked examples.
        </p>
        <span className={styles.soon}>API keys and limits coming with paid plans</span>
      </section>

      <section id="mcp" className={styles.card} aria-labelledby="mcp-heading">
        <h2 id="mcp-heading">MCP connector</h2>
        <p>
          Let Claude and other MCP clients use BenriSpace directly: score places, rank the
          best areas for your factors, find nearby places, compare similar areas and plan
          around several destinations.
        </p>
        <pre className={styles.code}>
          <code>{MCP_URL}</code>
        </pre>
        <p>
          In Claude, open Settings, then Connectors, choose Add custom connector and paste the
          URL above. No sign-in is needed.
        </p>
      </section>

      <section id="data" className={styles.card} aria-labelledby="data-heading">
        <h2 id="data-heading">Data sources</h2>
        <p>
          Every score is built from open data. <Link href="/data">See every source</Link>, its
          licence and when it was last refreshed.
        </p>
      </section>
    </InfoPage>
  );
}
