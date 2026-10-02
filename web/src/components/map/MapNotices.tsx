import { describeError } from "@/lib/api/messages";
import { formatCount } from "@/lib/map/presentation";

import styles from "./MapNotices.module.css";

interface MapNoticesProps {
  loading: boolean;
  noFactors: boolean;
  empty: boolean;
  truncated: boolean;
  count: number;
  error: Parameters<typeof describeError>[0] | null;
  retryAfter?: number;
  hasData: boolean;
  onRetry: () => void;
}

export function MapNotices({
  loading,
  noFactors,
  empty,
  truncated,
  count,
  error,
  retryAfter,
  hasData,
  onRetry,
}: MapNoticesProps) {
  const failure = error ? describeError(error) : null;
  return (
    <div className={styles.notices}>
      {loading ? <p className={styles.notice}>Updating scores…</p> : null}
      {noFactors ? (
        <p className={styles.notice}>Select a factor to color the map.</p>
      ) : null}
      {empty && !loading ? (
        <p className={styles.notice}>
          No scored cells in view. Pan or zoom out.
        </p>
      ) : null}
      {truncated ? (
        <p className={styles.notice}>
          Showing {formatCount(count)} cells. Zoom in for more detail.
        </p>
      ) : null}
      {failure ? (
        <div className={`${styles.notice} ${styles.noticeError}`}>
          <p>
            <strong>{failure.title}.</strong>
            {retryAfter ? ` Try again in ${retryAfter} seconds.` : ""}
            {hasData ? " Showing the last scores loaded." : ""}
          </p>
          {failure.retryable ? (
            <button
              type="button"
              className={styles.noticeButton}
              onClick={onRetry}
            >
              Try again
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
