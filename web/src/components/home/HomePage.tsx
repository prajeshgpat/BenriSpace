import Link from "next/link";

import { SiteFooter } from "@/components/SiteFooter";
import { FactorIcon } from "@/lib/factorIcons";
import { FACTOR_GUIDE, FACTOR_GUIDE_ORDER } from "@/lib/home/factorGuide";
import { scoreColor } from "@/lib/map/colors";
import { FACTORS } from "@/lib/score/factors";
import { APP_PATH } from "@/lib/site";

import { HomeSearch } from "./HomeSearch";
import styles from "./HomePage.module.css";

const STEPS = [
  {
    title: "Search",
    text: "Type an address in the New York metro area, or click the map.",
  },
  {
    title: "See the score",
    text: "Get one score out of 100, with a sub-score for every factor you pick.",
  },
  {
    title: "Understand why",
    text: "Each factor says what it measured, with distances in feet and miles.",
  },
] as const;

const COMING_SOON = ["AI explanations", "Similar areas", "Compare places"] as const;

const COLS = 16;
const ROWS = 7;
const CELL = 40;
const GAP = 8;

/** A smooth, deterministic field of scores so the backdrop reads like a heat map. */
const BACKDROP_CELLS = Array.from({ length: COLS * ROWS }, (_, i) => {
  const x = i % COLS;
  const y = Math.floor(i / COLS);
  const score =
    50 +
    28 * Math.sin(x * 0.55 + 0.6) * Math.cos(y * 0.8 - 0.4) +
    14 * Math.sin((x + y) * 0.9);
  return { x, y, fill: scoreColor(Math.max(0, Math.min(100, score))), i };
});

function Backdrop() {
  const w = COLS * (CELL + GAP) - GAP;
  const h = ROWS * (CELL + GAP) - GAP;
  return (
    <svg
      className={styles.backdrop}
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
      focusable="false"
    >
      {BACKDROP_CELLS.map((c) => (
        <rect
          key={c.i}
          className={styles.cell}
          style={{ animationDelay: `${(c.i % 11) * -0.9}s` }}
          x={c.x * (CELL + GAP)}
          y={c.y * (CELL + GAP)}
          width={CELL}
          height={CELL}
          rx={10}
          fill={c.fill}
        />
      ))}
    </svg>
  );
}

/** The static landing page: a search, what is scored and how it works. */
export function HomePage() {
  return (
    <>
      <main id="main" className={styles.main}>
        <header className={styles.hero}>
          <Backdrop />
          <p className={styles.eyebrow}>Benri (便利) means convenient</p>
          <h1 className={styles.title}>How convenient is that address?</h1>
          <p className={styles.lead}>
            A score out of 100 for any place in the New York metro area.
          </p>
          <HomeSearch />
          <Link className={styles.quiet} href={APP_PATH} prefetch={false}>
            Explore the map
          </Link>
        </header>

        <section className={styles.section} aria-labelledby="what-we-score">
          <h2 id="what-we-score" className={styles.heading}>
            What we score
          </h2>
          <ul className={styles.factors}>
            {FACTOR_GUIDE_ORDER.map((key) => (
              <li key={key} className={styles.factor} data-factor={key}>
                <FactorIcon factor={key} className={styles.icon} aria-hidden="true" />
                <h3 className={styles.factorName}>{FACTORS[key].label}</h3>
                <p className={styles.factorText}>{FACTOR_GUIDE[key].blurb}</p>
              </li>
            ))}
          </ul>
        </section>

        <section className={styles.section} aria-labelledby="how-it-works">
          <h2 id="how-it-works" className={styles.heading}>
            How it works
          </h2>
          <ol className={styles.steps}>
            {STEPS.map((step, index) => (
              <li key={step.title} className={styles.step}>
                <span className={styles.numeral} aria-hidden="true">
                  {index + 1}
                </span>
                <h3 className={styles.stepTitle}>{step.title}</h3>
                <p className={styles.stepText}>{step.text}</p>
              </li>
            ))}
          </ol>
        </section>

        <section className={styles.soon} aria-labelledby="coming-soon">
          <h2 id="coming-soon" className={styles.soonLabel}>
            Coming soon
          </h2>
          <ul className={styles.soonList}>
            {COMING_SOON.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>

        <section className={styles.closing} aria-labelledby="start">
          <h2 id="start" className={styles.closingTitle}>
            See your neighborhood in color.
          </h2>
          <Link className={styles.cta} href={APP_PATH} prefetch={false}>
            Open the app
          </Link>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
