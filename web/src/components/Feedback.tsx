"use client";

import { useId, useState } from "react";

import type { ApiClient } from "@/lib/api/client";
import type { Feedback } from "@/lib/api/types";

import styles from "./Feedback.module.css";

type Sender = Partial<Pick<ApiClient, "sendFeedback">>;

/** Fire and forget: feedback must never show an error or block anything. */
function send(client: Sender | undefined, feedback: Feedback) {
  try {
    void Promise.resolve(client?.sendFeedback?.(feedback)).catch(() => {});
  } catch {
    // Silent by design.
  }
}

const clip = (text: string, max: number) => text.trim().slice(0, max);

interface ThumbsProps {
  client?: Sender;
  kind: "summary" | "chat";
  /** The place or the start of the answer being rated. */
  target: string;
}

/** "Was this helpful?" under an AI summary or chat reply. */
export function FeedbackThumbs({ client, kind, target }: ThumbsProps) {
  const [sent, setSent] = useState(false);
  if (!client?.sendFeedback) return null;
  if (sent) {
    return (
      <p className={styles.thanks} role="status">
        Thanks, that helps us improve.
      </p>
    );
  }
  const rate = (rating: 1 | -1) => {
    send(client, { kind, rating, target: clip(target, 200) });
    setSent(true);
  };
  return (
    <div className={styles.row} role="group" aria-label="Was this helpful?">
      <span>Was this helpful?</span>
      <button type="button" className={styles.button} onClick={() => rate(1)}>
        Yes
        <span className="sr-only">, this was helpful</span>
      </button>
      <button type="button" className={styles.button} onClick={() => rate(-1)}>
        No
        <span className="sr-only">, this was not helpful</span>
      </button>
    </div>
  );
}

interface ReportProps {
  client?: Sender;
  /** Which list, e.g. "Best areas". */
  list: string;
}

/** A small form for "this place is closed / wrong", under a list of places. */
export function ReportProblem({ client, list }: ReportProps) {
  const [open, setOpen] = useState(false);
  const [done, setDone] = useState(false);
  const [reason, setReason] = useState<"wrong" | "closed">("wrong");
  const [note, setNote] = useState("");
  const id = useId();
  if (!client?.sendFeedback) return null;
  if (done) {
    return (
      <p className={styles.thanks} role="status">
        Thanks, we&rsquo;ll take a look.
      </p>
    );
  }
  if (!open) {
    return (
      <p className={styles.row}>
        <button type="button" className={styles.link} onClick={() => setOpen(true)}>
          Report a problem
        </button>
        <span className="sr-only"> with {list}</span>
      </p>
    );
  }
  return (
    <form
      className={styles.form}
      aria-label={`Report a problem with ${list}`}
      onSubmit={(event) => {
        event.preventDefault();
        send(client, {
          kind: "place",
          target: clip(`${list}: ${reason}`, 200),
          rating: -1,
          message: clip(`${reason}. ${note}`, 1000),
        });
        setDone(true);
      }}
    >
      <fieldset>
        <legend>What is wrong?</legend>
        <label>
          <input
            type="radio"
            name={`${id}-reason`}
            checked={reason === "wrong"}
            onChange={() => setReason("wrong")}
          />{" "}
          A place is wrong or in the wrong spot
        </label>
        <label>
          <input
            type="radio"
            name={`${id}-reason`}
            checked={reason === "closed"}
            onChange={() => setReason("closed")}
          />{" "}
          A place has closed
        </label>
      </fieldset>
      <label htmlFor={`${id}-note`}>Which place? (optional)</label>
      <textarea
        id={`${id}-note`}
        value={note}
        maxLength={500}
        onChange={(event) => setNote(event.target.value)}
      />
      <div className={styles.row}>
        <button type="submit" className={styles.button}>
          Send report
        </button>
        <button type="button" className={styles.button} onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
    </form>
  );
}
