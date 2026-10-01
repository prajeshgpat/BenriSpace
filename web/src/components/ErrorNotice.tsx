import type { ApiError } from "@/lib/api/errors";
import { describeError } from "@/lib/api/messages";

import styles from "./ErrorNotice.module.css";

interface ErrorNoticeProps {
  address: string;
  error: ApiError;
  onRetry: () => void;
}

export function ErrorNotice({ address, error, onRetry }: ErrorNoticeProps) {
  const { title, body, retryable } = describeError(error.kind);

  return (
    <section className={styles.notice} role="alert" data-kind={error.kind}>
      <svg
        className={styles.icon}
        viewBox="0 0 24 24"
        aria-hidden="true"
        focusable="false"
      >
        <circle cx="12" cy="12" r="9.25" />
        <path d="M12 7.5v5.5" />
        <circle className={styles.iconDot} cx="12" cy="16.25" r="0.9" />
      </svg>
      <div className={styles.content}>
        <h2 className={styles.title}>{title}</h2>
        <p className={styles.address}>&ldquo;{address}&rdquo;</p>
        <p className={styles.body}>{body}</p>
        {retryable ? (
          <button className={styles.retry} type="button" onClick={onRetry}>
            Try again
          </button>
        ) : null}
      </div>
    </section>
  );
}
