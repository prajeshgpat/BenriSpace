"use client";

import { useState } from "react";

import { useResource } from "@/hooks/useResource";
import { createApiClient, type ApiClient } from "@/lib/api/client";
import { API_BASE_URL } from "@/lib/config";
import { daysAgo } from "@/lib/timeAgo";

import styles from "./DataSources.module.css";

const defaultClient = createApiClient({ baseUrl: API_BASE_URL });

/** The data transparency table: each source, what it feeds, its licence and freshness. */
export function DataSources({
  client = defaultClient,
}: {
  client?: Pick<ApiClient, "getSources">;
}) {
  const sources = useResource("sources", (signal) => client.getSources({ signal }));
  const [now] = useState(() => new Date());

  if (sources.status === "error" && !sources.data) {
    return (
      <p role="alert" className={styles.note}>
        The list of sources couldn&rsquo;t be loaded.{" "}
        <button type="button" className={styles.retry} onClick={sources.retry}>
          Try again
        </button>
      </p>
    );
  }
  if (!sources.data) {
    return (
      <p role="status" className={styles.note}>
        Loading sources&hellip;
      </p>
    );
  }
  return (
    <div className={styles.scroll}>
      <table className={styles.table}>
        <caption className="sr-only">Data sources behind BenriSpace scores</caption>
        <thead>
          <tr>
            <th scope="col">Source</th>
            <th scope="col">What it feeds</th>
            <th scope="col">Licence</th>
            <th scope="col">Last updated</th>
          </tr>
        </thead>
        <tbody>
          {sources.data.map((source) => (
            <tr key={source.name}>
              <th scope="row">{source.name}</th>
              <td>{source.feeds ?? "—"}</td>
              <td>
                {source.licenseUrl ? (
                  <a href={source.licenseUrl} target="_blank" rel="noreferrer">
                    {source.license ?? "Licence"}
                  </a>
                ) : (
                  (source.license ?? "—")
                )}
              </td>
              <td>
                <time dateTime={source.lastUpdated ?? undefined}>
                  {daysAgo(source.lastUpdated, now)}
                </time>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
