import styles from "./Diagrams.module.css";

/**
 * Inline SVG diagrams for the landing page. They are static, take their
 * colours from the theme tokens (so they read in light and dark) and are
 * illustrative: no real places or counts.
 */

const FACTOR_BARS = [9, 7, 5, 6, 4, 5, 8, 3, 4, 3, 6, 4, 3];

/** The score: rings of nearby places fading out, 13 weighted factors, a 0-100 dial. */
export function ScoreDiagram({ label }: { label: string }) {
  return (
    <svg className={styles.svg} viewBox="0 0 480 340" role="img" aria-label={label}>
      <rect className={styles.panel} x="0.5" y="0.5" width="479" height="339" rx="16" />
      {[100, 76, 50, 24].map((r, i) => (
        <circle
          key={r}
          className={styles.ring}
          cx="105"
          cy="110"
          r={r}
          fillOpacity={0.05 + i * 0.09}
          strokeOpacity={0.15 + i * 0.12}
        />
      ))}
      {[
        [70, 80],
        [140, 70],
        [60, 135],
        [150, 140],
        [105, 52],
        [105, 168],
        [42, 100],
        [172, 100],
      ].map(([x, y]) => (
        <circle key={`${x}-${y}`} className={styles.dot} cx={x} cy={y} r="4" />
      ))}
      <circle className={styles.pin} cx="105" cy="110" r="10" />
      <text className={styles.label} x="105" y="228" textAnchor="middle">
        Nearby counts
      </text>
      <text className={styles.labelSub} x="105" y="248" textAnchor="middle">
        fade with distance
      </text>

      <path className={styles.flow} d="M 195 110 C 230 110 250 110 290 110" />
      <circle className={styles.track} cx="375" cy="110" r="56" />
      <circle className={styles.arc} cx="375" cy="110" r="56" transform="rotate(-90 375 110)" />
      <text className={styles.dialNum} x="375" y="124" textAnchor="middle">
        78
      </text>
      <text className={styles.labelSub} x="375" y="206" textAnchor="middle">
        out of 100
      </text>

      {FACTOR_BARS.map((h, i) => (
        <rect
          key={i}
          className={styles.bar}
          x={22 + i * 34.5}
          y={320 - h * 4}
          width="24"
          height={h * 4}
          rx="5"
        />
      ))}
      <path className={styles.flow} d="M 300 262 C 330 240 360 230 370 212" />
      <text className={styles.labelSub} x="22" y="266">
        13 factors, weighted
      </text>
    </svg>
  );
}

const MAP_ROADS = [
  "M 0 60 L 480 90",
  "M 0 200 L 480 170",
  "M 0 290 L 480 300",
  "M 90 0 L 70 340",
  "M 250 0 L 270 340",
  "M 400 0 L 420 340",
];

/** Triangulation: three travel-time areas, their overlap and the best areas in it. */
export function TriangulationDiagram({ label }: { label: string }) {
  return (
    <svg className={styles.svg} viewBox="0 0 480 340" role="img" aria-label={label}>
      <defs>
        <clipPath id="tri-work">
          <ellipse cx="160" cy="130" rx="120" ry="95" />
        </clipPath>
        <clipPath id="tri-family">
          <ellipse cx="320" cy="130" rx="120" ry="95" />
        </clipPath>
        <clipPath id="tri-gym">
          <ellipse cx="240" cy="240" rx="125" ry="85" />
        </clipPath>
      </defs>
      <rect className={styles.panel} x="0.5" y="0.5" width="479" height="339" rx="16" />
      {MAP_ROADS.map((d) => (
        <path key={d} className={styles.road} d={d} />
      ))}
      <ellipse className={styles.blobA} cx="160" cy="130" rx="120" ry="95" />
      <ellipse className={styles.blobB} cx="320" cy="130" rx="120" ry="95" />
      <ellipse className={styles.blobC} cx="240" cy="240" rx="125" ry="85" />
      <g clipPath="url(#tri-work)">
        <g clipPath="url(#tri-family)">
          <g clipPath="url(#tri-gym)">
            <rect className={styles.overlap} x="0" y="0" width="480" height="340" />
          </g>
        </g>
      </g>
      {[
        [228, 160],
        [254, 158],
        [241, 184],
      ].map(([x, y]) => (
        <circle key={`${x}-${y}`} className={styles.best} cx={x} cy={y} r="10" />
      ))}
      <text className={`${styles.labelSub} ${styles.halo}`} x="241" y="224" textAnchor="middle">
        Best areas
      </text>
      {[
        { x: 105, y: 112, t: "Work" },
        { x: 375, y: 112, t: "Family" },
        { x: 240, y: 290, t: "Gym" },
      ].map((a) => (
        <g key={a.t}>
          <circle className={styles.anchor} cx={a.x} cy={a.y} r="8" />
          <text
            className={`${styles.label} ${styles.halo}`}
            x={a.x}
            y={a.y - 18}
            textAnchor="middle"
          >
            {a.t}
          </text>
        </g>
      ))}
    </svg>
  );
}

/** Trips per week set the line weight only; the numbers shown are minutes. */
const ANCHORS = [
  { t: "Work", x: 400, y: 52, w: 5 },
  { t: "Groceries", x: 108, y: 296, w: 2 },
  { t: "Gym", x: 400, y: 296, w: 1 },
] as const;
const CANDIDATES = [
  { id: "a", x: 60, y: 150, win: false, commute: "31 min", labelX: 60, labelY: 192 },
  { id: "b", x: 235, y: 175, win: true, commute: "", labelX: 0, labelY: 0 },
  { id: "c", x: 375, y: 200, win: false, commute: "27 min", labelX: 428, labelY: 206 },
] as const;
/** Minutes from the winning area to each stop, placed on the line midpoint. */
const WIN_MINUTES: Record<string, { text: string; x: number; y: number }> = {
  Work: { text: "18 min", x: 317, y: 120 },
  Groceries: { text: "7 min", x: 172, y: 240 },
  Gym: { text: "8 min", x: 317, y: 240 },
};
const PILL_W = 124;

/**
 * Optimization: candidate home areas, the commute in minutes to Work, and the
 * winner's short trips to everyday stops. Line weight is how often a trip is made.
 */
export function OptimizationDiagram({ label }: { label: string }) {
  return (
    <svg className={styles.svg} viewBox="0 0 480 340" role="img" aria-label={label}>
      <rect className={styles.panel} x="0.5" y="0.5" width="479" height="339" rx="16" />
      {CANDIDATES.flatMap((c) =>
        ANCHORS.map((a) => (
          <line
            key={`${c.id}-${a.t}`}
            className={c.win ? styles.lineWin : styles.lineDim}
            x1={a.x}
            y1={a.y}
            x2={c.x}
            y2={c.y}
            strokeWidth={a.w * 1.8 + 1}
          />
        )),
      )}
      {CANDIDATES.map((c) => (
        <g key={c.id}>
          {c.win && <circle className={styles.winRing} cx={c.x} cy={c.y} r="26" />}
          <circle className={c.win ? styles.win : styles.cand} cx={c.x} cy={c.y} r="14" />
          {!c.win && (
            <text
              className={`${styles.labelSub} ${styles.halo}`}
              x={c.labelX}
              y={c.labelY}
              textAnchor="middle"
            >
              {c.commute}
            </text>
          )}
        </g>
      ))}
      {ANCHORS.map((a) => (
        <text
          key={`m-${a.t}`}
          className={`${styles.label} ${styles.halo}`}
          x={WIN_MINUTES[a.t].x}
          y={WIN_MINUTES[a.t].y}
          textAnchor="middle"
        >
          {WIN_MINUTES[a.t].text}
        </text>
      ))}
      <text className={`${styles.label} ${styles.halo}`} x="235" y="136" textAnchor="middle">
        Best fit
      </text>
      {ANCHORS.map((a) => (
        <g key={a.t}>
          <rect
            className={styles.pill}
            x={a.x - PILL_W / 2}
            y={a.y - 18}
            width={PILL_W}
            height="36"
            rx="18"
          />
          <text className={styles.label} x={a.x} y={a.y + 7} textAnchor="middle">
            {a.t}
          </text>
        </g>
      ))}
      <line className={styles.lineWin} x1="20" y1="30" x2="52" y2="30" strokeWidth="9" />
      <text className={styles.labelSub} x="62" y="37">
        Thicker = more often
      </text>
    </svg>
  );
}

/* Small illustrations for the "What you get" cards (viewBox 160 x 96). */

export function ScoreIllustration() {
  return (
    <svg className={styles.svg} viewBox="0 0 160 96" aria-hidden="true" focusable="false">
      <circle className={styles.track} cx="80" cy="50" r="34" strokeWidth="9" />
      <circle
        className={styles.arc}
        cx="80"
        cy="50"
        r="34"
        strokeWidth="9"
        transform="rotate(-90 80 50)"
        style={{ animation: "none", strokeDasharray: "167 214" }}
      />
      <text className={styles.dialNum} x="80" y="61" textAnchor="middle" style={{ fontSize: 28 }}>
        87
      </text>
      {[16, 30, 130, 144].map((x, i) => (
        <rect
          key={x}
          className={styles.bar}
          x={x - 5}
          y={78 - (i % 2 ? 22 : 34)}
          width="10"
          height={i % 2 ? 22 : 34}
          rx="3"
        />
      ))}
    </svg>
  );
}

export function NeighborhoodsIllustration() {
  return (
    <svg className={styles.svg} viewBox="0 0 160 96" aria-hidden="true" focusable="false">
      <path className={styles.tile} d="M 10 12 L 56 8 L 62 40 L 14 46 Z" />
      <path className={styles.tileA} d="M 62 40 L 56 8 L 104 14 L 112 52 L 80 58 Z" />
      <path className={styles.tile} d="M 104 14 L 150 10 L 148 48 L 112 52 Z" />
      <path className={styles.tile} d="M 14 46 L 62 40 L 80 58 L 74 88 L 18 86 Z" />
      <path className={styles.tile} d="M 80 58 L 112 52 L 148 48 L 150 88 L 74 88 Z" />
      <circle className={styles.pin} cx="84" cy="34" r="6" />
    </svg>
  );
}

export function StopsIllustration() {
  const stops = [
    [22, 20],
    [28, 76],
    [138, 48],
  ];
  return (
    <svg className={styles.svg} viewBox="0 0 160 96" aria-hidden="true" focusable="false">
      {stops.map(([x, y], i) => (
        <line
          key={`l${i}`}
          className={styles.lineWin}
          x1={x}
          y1={y}
          x2="84"
          y2="48"
          strokeWidth={[5, 3, 2][i]}
        />
      ))}
      {stops.map(([x, y]) => (
        <circle key={`${x}-${y}`} className={styles.anchor} cx={x} cy={y} r="7" />
      ))}
      <circle className={styles.winRing} cx="84" cy="48" r="17" />
      <circle className={styles.win} cx="84" cy="48" r="10" />
    </svg>
  );
}

export function ReachIllustration() {
  return (
    <svg className={styles.svg} viewBox="0 0 160 96" aria-hidden="true" focusable="false">
      <path
        className={styles.car}
        d="M 80 6 C 112 4 150 22 152 50 C 154 80 112 92 78 90 C 40 90 8 76 10 46 C 12 20 46 8 80 6 Z"
      />
      <path
        className={styles.train}
        d="M 80 20 C 104 18 130 30 132 50 C 133 70 106 78 80 76 C 54 76 28 66 30 48 C 32 32 56 22 80 20 Z"
      />
      <path
        className={styles.walk}
        d="M 80 34 C 94 33 106 40 106 50 C 106 60 94 64 80 63 C 66 63 54 58 55 49 C 56 41 66 35 80 34 Z"
      />
      <circle className={styles.pin} cx="80" cy="49" r="6" />
    </svg>
  );
}

/* Group icons for the "What we score" cards (24 x 24, drawn with currentColor). */

const GLYPH = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round",
  strokeLinejoin: "round",
} as const;

export function GroupIcon({
  group,
  className,
}: {
  group: "amenities" | "mobility" | "neighborhood";
  className?: string;
}) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true" focusable="false" {...GLYPH}>
      {group === "amenities" && <path d="M5 8h14l-1.2 11H6.2zM9 8V6a3 3 0 0 1 6 0v2" />}
      {group === "mobility" && (
        <path d="M7 4h10a2 2 0 0 1 2 2v9a3 3 0 0 1-3 3H8a3 3 0 0 1-3-3V6a2 2 0 0 1 2-2zM5 11h14M9 21l-2 1M15 21l2 1M8.5 15h.01M15.5 15h.01" />
      )}
      {group === "neighborhood" && <path d="M3 11.5 12 4l9 7.5M5.5 10v10h13V10M10 20v-5h4v5" />}
    </svg>
  );
}

export function ExtraIcon({
  name,
  className,
}: {
  name: "compare" | "similar" | "improve";
  className?: string;
}) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true" focusable="false" {...GLYPH}>
      {name === "compare" && <path d="M4 4h7v16H4zM13 4h7v16h-7z" />}
      {name === "similar" && <path d="M4 5h9v9H4zM11 10h9v9h-9z" />}
      {name === "improve" && <path d="M12 20V6M6 12l6-6 6 6" />}
    </svg>
  );
}
