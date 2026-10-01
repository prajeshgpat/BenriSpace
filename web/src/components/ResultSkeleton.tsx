import styles from "./ResultSkeleton.module.css";

const PLACEHOLDER_ROWS = 5;

/** Purely visual; the loading announcement lives in ScoreExplorer's live region. */
export function ResultSkeleton() {
  return (
    <div className={styles.card} aria-hidden="true" data-testid="result-skeleton">
      <div className={`${styles.block} ${styles.heading}`} />
      <div className={styles.summary}>
        <div className={`${styles.block} ${styles.ring}`} />
        <div className={styles.lines}>
          <div className={`${styles.block} ${styles.line}`} />
          <div className={`${styles.block} ${styles.lineShort}`} />
        </div>
      </div>
      {Array.from({ length: PLACEHOLDER_ROWS }, (_, index) => (
        <div key={index} className={`${styles.block} ${styles.row}`} />
      ))}
    </div>
  );
}
