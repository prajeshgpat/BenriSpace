"use client";

import { useEffect, useState } from "react";

import styles from "./CopyLinkButton.module.css";

type CopyStatus = "idle" | "copied" | "failed";

const FEEDBACK_MS = 2500;

const LABELS: Record<CopyStatus, string> = {
  idle: "Copy link",
  copied: "Link copied",
  failed: "Copy failed",
};

export function CopyLinkButton() {
  const [status, setStatus] = useState<CopyStatus>("idle");

  useEffect(() => {
    if (status === "idle") return;
    const timer = setTimeout(() => setStatus("idle"), FEEDBACK_MS);
    return () => clearTimeout(timer);
  }, [status]);

  async function handleClick() {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setStatus("copied");
    } catch {
      // Clipboard access can be denied or missing (insecure origin); the URL
      // in the address bar is still the shareable link.
      setStatus("failed");
    }
  }

  return (
    <button className={styles.button} type="button" onClick={handleClick}>
      <span aria-live="polite">{LABELS[status]}</span>
    </button>
  );
}
