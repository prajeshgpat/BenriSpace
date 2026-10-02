import styles from "./LocateButton.module.css";

interface LocateButtonProps {
  variant: "field" | "map";
  locating: boolean;
  disabled?: boolean;
  describedBy?: string;
  onClick: () => void;
}

export function LocateButton({
  variant,
  locating,
  disabled = false,
  describedBy,
  onClick,
}: LocateButtonProps) {
  const label = locating ? "Locating…" : "Use my current location";
  return (
    <button
      type="button"
      className={styles[variant]}
      onClick={onClick}
      disabled={disabled || locating}
      aria-busy={locating || undefined}
      aria-describedby={describedBy}
      aria-label={label}
      title={label}
    >
      <svg
        className={styles.icon}
        viewBox="0 0 24 24"
        aria-hidden="true"
        focusable="false"
        data-spinning={locating || undefined}
      >
        <circle cx="12" cy="12" r="6.5" />
        <circle className={styles.dot} cx="12" cy="12" r="1.75" />
        <path d="M12 2v4M12 18v4M2 12h4M18 12h4" />
      </svg>
    </button>
  );
}
