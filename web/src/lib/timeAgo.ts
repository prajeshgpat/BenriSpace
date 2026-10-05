const DAY_MS = 86_400_000;

/** "today", "1 day ago", "12 days ago"; "unknown" for a missing or unreadable date. */
export function daysAgo(iso: string | null, now: Date = new Date()): string {
  if (!iso) return "unknown";
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "unknown";
  const days = Math.floor((now.getTime() - then) / DAY_MS);
  if (days <= 0) return "today";
  return days === 1 ? "1 day ago" : `${days} days ago`;
}
