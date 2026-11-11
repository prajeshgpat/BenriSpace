import type { CSSProperties } from "react";

import type { ChatResult } from "@/lib/api/types";
import { scoreColor } from "@/lib/map/colors";

import styles from "./ChatPanel.module.css";

/** "35 min commute": one-way minutes to the main address, never a weekly total. */
export function commuteText(result: ChatResult): string | null {
  return result.commuteMinutes === undefined
    ? null
    : `${Math.round(result.commuteMinutes)} min commute`;
}

/** The plain-text facts line, also read out by screen readers. */
export function resultFacts(result: ChatResult): string {
  const facts: string[] = [];
  if (result.score !== undefined) facts.push(`Score ${Math.round(result.score)}`);
  const commute = commuteText(result);
  if (commute) facts.push(commute);
  return facts.join(" · ");
}

interface ResultCardProps {
  result: ChatResult;
  rank: number;
  onShowOnMap: (result: ChatResult) => void;
  onScoreArea: (result: ChatResult) => void;
}

export function ResultCard({ result, rank, onShowOnMap, onScoreArea }: ResultCardProps) {
  const facts = resultFacts(result);
  const badgeStyle =
    result.score !== undefined
      ? ({ "--badge-color": scoreColor(result.score) } as CSSProperties)
      : undefined;
  return (
    <li className={styles.card}>
      <div className={styles.cardTop}>
        <span className={styles.rank} aria-hidden="true">
          {rank}
        </span>
        <div className={styles.cardHead}>
          <p className={styles.cardTitle}>{result.label}</p>
          {facts ? <p className="sr-only">{facts}</p> : null}
          {commuteText(result) ? (
            <p className={styles.cardFacts} aria-hidden="true">
              {commuteText(result)}
            </p>
          ) : null}
        </div>
        {result.score !== undefined ? (
          <span className={styles.badge} style={badgeStyle} aria-hidden="true">
            {Math.round(result.score)}
          </span>
        ) : null}
      </div>
      <p className={styles.cardWhy}>{result.why}</p>
      <div className={styles.cardActions}>
        <button
          type="button"
          className={styles.action}
          onClick={() => onShowOnMap(result)}
          aria-label={`Show ${result.label} on map`}
        >
          Show on map
        </button>
        <button
          type="button"
          className={styles.action}
          onClick={() => onScoreArea(result)}
          aria-label={`Score ${result.label}`}
        >
          Score this area
        </button>
      </div>
    </li>
  );
}
