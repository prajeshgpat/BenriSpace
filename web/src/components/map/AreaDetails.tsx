import Link from "next/link";

import { coordinatesHref } from "@/lib/address";
import { scoreColor } from "@/lib/map/colors";
import { roundScore } from "@/lib/score/presentation";

import styles from "./AreaDetails.module.css";

export interface DetailRow {
  key: string;
  label: string;
  value: number | null;
}

interface AreaDetailsProps {
  /** Omitted where a heading already names the area. */
  title?: string;
  score: number;
  /** What the score is computed from, e.g. "4 selected factors". */
  basis: string;
  rows: readonly DetailRow[];
  /** Shows only the strongest rows and points to the full breakdown for the rest. */
  maxRows?: number;
  lat: number;
  lon: number;
}

/**
 * Shared by the map popup and the best-areas list, so a keyboard or
 * screen-reader user can reach the same area, score and breakdown that a
 * pointer user gets from the map.
 */
export function AreaDetails({
  title,
  score,
  basis,
  rows,
  maxRows,
  lat,
  lon,
}: AreaDetailsProps) {
  const rounded = roundScore(score);
  const capped = maxRows !== undefined && rows.length > maxRows;
  const shown = capped
    ? [...rows]
        .sort((a, b) => (b.value ?? -1) - (a.value ?? -1))
        .slice(0, maxRows)
    : rows;
  return (
    <div className={styles.details}>
      {title ? <p className={styles.title}>{title}</p> : null}
      <p className={styles.score}>
        <span
          className={styles.swatch}
          style={{ background: scoreColor(score) }}
          aria-hidden="true"
        />
        <strong>{rounded}</strong>
        <span className={styles.max}> out of 100</span>
        <span className={styles.basis}> · {basis}</span>
      </p>
      {shown.length > 0 ? (
        <ul className={styles.rows}>
          {shown.map((row) => (
            <li key={row.key} className={styles.row}>
              <span>{row.label}</span>
              <span className={styles.value}>
                {row.value === null ? "No data" : roundScore(row.value)}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {capped ? (
        <p className={styles.more}>
          Top {maxRows} of {rows.length} factors shown.
        </p>
      ) : null}
      <Link
        className={styles.link}
        href={coordinatesHref({ lat, lon })}
        prefetch={false}
      >
        Full breakdown
      </Link>
    </div>
  );
}
