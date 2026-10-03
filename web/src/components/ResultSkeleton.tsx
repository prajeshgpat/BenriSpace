import styles from "./ResultSkeleton.module.css";

/** Purely visual; the loading announcement lives in ScoreExplorer's live region. */
export function ResultSkeleton() {
  return (
    <div className={styles.card} aria-hidden="true" data-testid="result-skeleton">
      <div className={`${styles.block} ${styles.ring}`} />
      <div className={styles.lines}>
        <div className={`${styles.block} ${styles.line}`} />
        <div className={`${styles.block} ${styles.heading}`} />
        <div className={`${styles.block} ${styles.lineShort}`} />
      </div>
    </div>
  );
}
