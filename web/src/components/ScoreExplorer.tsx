"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, type MouseEvent } from "react";

import { useScoreLookup, type LookupState } from "@/hooks/useScoreLookup";
import {
  ADDRESS_PARAM,
  resolveTarget,
  resultHref,
  targetKey,
  targetLabel,
} from "@/lib/address";
import { createApiClient, type ApiClient } from "@/lib/api/client";
import type { Suggestion } from "@/lib/api/types";
import { API_BASE_URL } from "@/lib/config";
import { bandLabel, roundScore } from "@/lib/score/presentation";
import { EXAMPLE_ADDRESSES, SITE_TITLE, resultTitle } from "@/lib/site";

import { AddressSearch } from "./AddressSearch";
import { ErrorNotice } from "./ErrorNotice";
import { ResultSkeleton } from "./ResultSkeleton";
import { ScoreResult } from "./ScoreResult";
import styles from "./ScoreExplorer.module.css";

const defaultClient = createApiClient({ baseUrl: API_BASE_URL });

function announcement(state: LookupState): string {
  switch (state.status) {
    case "loading":
      return `Scoring ${state.address}…`;
    case "success": {
      const { compositeScore } = state.score;
      return `${state.address} scores ${roundScore(compositeScore)} out of 100, ${bandLabel(compositeScore)}.`;
    }
    default:
      return "";
  }
}

function isModifiedClick(event: MouseEvent): boolean {
  return (
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  );
}

interface ScoreExplorerProps {
  client?: ApiClient;
}

export function ScoreExplorer({ client = defaultClient }: ScoreExplorerProps) {
  const params = useSearchParams();
  const rawAddress = params.get(ADDRESS_PARAM);
  const { target, error: urlError } = resolveTarget(params);
  const address = target ? targetLabel(target) : null;

  const { state, retry } = useScoreLookup(target, client);

  // Deliberately runs after every commit: on a direct load of a result URL
  // Next hydrates its own <title> after this component's first effect and
  // would otherwise leave the generic site title in place.
  useEffect(() => {
    document.title = address ? resultTitle(address) : SITE_TITLE;
  });

  function navigate(href: string) {
    const next = resolveTarget(new URLSearchParams(href.slice(href.indexOf("?"))));
    if (next.target && target && targetKey(next.target) === targetKey(target)) {
      retry();
      return;
    }
    // The page is static and the lookup runs in the browser, so there is
    // nothing to fetch from the Next.js server. Native pushState keeps
    // useSearchParams in sync without an RSC round trip, and without the
    // router moving focus to the top of the page.
    window.history.pushState(null, "", href);
  }

  const handleSearch = (next: string) => navigate(resultHref(next));

  const handleSelectSuggestion = ({ label, latitude, longitude }: Suggestion) =>
    navigate(resultHref(label, { lat: latitude, lon: longitude }));

  return (
    <>
      <div className={styles.search}>
        <AddressSearch
          initialValue={rawAddress ?? (address ?? "")}
          initialError={urlError}
          onSearch={handleSearch}
          onSelectSuggestion={handleSelectSuggestion}
          suggestClient={client}
        />
        <p className={styles.examples}>
          <span className={styles.examplesLabel}>Try</span>
          {EXAMPLE_ADDRESSES.map((example) => (
            <Link
              key={example}
              className={styles.example}
              href={resultHref(example)}
              prefetch={false}
              onClick={(event) => {
                if (isModifiedClick(event)) return;
                event.preventDefault();
                handleSearch(example);
              }}
            >
              {example}
            </Link>
          ))}
        </p>
      </div>

      <p className="sr-only" role="status">
        {announcement(state)}
      </p>

      {state.status === "idle" ? <IdleIntro /> : null}
      {state.status === "loading" ? <ResultSkeleton /> : null}
      {state.status === "error" ? (
        <ErrorNotice
          address={state.address}
          error={state.error}
          onRetry={retry}
        />
      ) : null}
      {state.status === "success" ? (
        <ScoreResult
          address={state.address}
          score={state.score}
          explanation={state.explanation}
        />
      ) : null}
    </>
  );
}

function IdleIntro() {
  return (
    <section className={styles.idle} aria-labelledby="idle-heading">
      <h2 id="idle-heading" className={styles.idleHeading}>
        What you&rsquo;ll see
      </h2>
      <ul className={styles.idleList}>
        <li>
          <strong>One score out of 100</strong>
          <span>
            A weighted blend of everything below, relative to the rest of the
            metro area.
          </span>
        </li>
        <li>
          <strong>A factor-by-factor breakdown</strong>
          <span>
            Groceries, gyms, cafes, transit, schools, trails, airport access,
            roads and more, each scored separately.
          </span>
        </li>
        <li>
          <strong>A plain-language explanation</strong>
          <span>What is pulling the score up, and what is holding it back.</span>
        </li>
      </ul>
    </section>
  );
}
