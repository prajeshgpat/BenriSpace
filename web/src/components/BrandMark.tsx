/** The BenriSpace logo mark. Decorative: the wordmark beside it names the link. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 32 32"
      aria-hidden="true"
      focusable="false"
    >
      <rect width="32" height="32" rx="8" fill="currentColor" />
      <circle
        cx="16"
        cy="16"
        r="8"
        fill="none"
        stroke="#ffffff"
        strokeWidth="3"
      />
      <circle cx="16" cy="16" r="2.5" fill="#ffffff" />
    </svg>
  );
}
