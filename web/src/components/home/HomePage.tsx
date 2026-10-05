import Link from "next/link";

import { SiteFooter } from "@/components/SiteFooter";
import { FactorIcon } from "@/lib/factorIcons";
import { FACTOR_GUIDE, FACTOR_GUIDE_ORDER } from "@/lib/home/factorGuide";
import { scoreColor } from "@/lib/map/colors";
import { FACTORS, FACTOR_GROUPS, type FactorGroup } from "@/lib/score/factors";
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
    text: "Get one score out of 100, with a sub-score for every factor you pick, shown in feet and miles.",
  },
  {
    title: "Make it yours",
    text: "Weight what matters, ask how to improve an area, find similar neighborhoods or plan several stops at once.",
  },
] as const;

const BENEFITS = [
  {
    title: "One score from 13 factors",
    text: "A score out of 100 built from the factors you choose, from groceries and cafes to transit, schools and noise.",
  },
  {
    title: "Real neighborhoods",
    text: "Areas are polygons bounded by real streets and named for the neighborhood, not arbitrary squares.",
  },
  {
    title: "Plain-language summary",
    text: "An AI-written summary explains what drives a score, using only that area's data.",
  },
  {
    title: "Improve this area",
    text: "See which nearby additions would lift a score, with named places on the map.",
  },
  {
    title: "Similar neighborhoods",
    text: "Find other areas that feel like the one you like, wherever they are.",
  },
  {
    title: "Plan multiple stops",
    text: "Near work, Trader Joe's and Planet Fitness at once? The optimizer ranks areas by total travel.",
  },
  {
    title: "The right way to travel",
    text: "Walking and transit in dense areas, driving in the suburbs, so each place is judged fairly.",
  },
] as const;

const GROUP_ORDER: readonly FactorGroup[] = ["amenities", "mobility", "neighborhood"];

const DATA_SOURCES = "OpenStreetMap, transit agency feeds, the U.S. Census and public school data";

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
          <p className={styles.eyebrow}>Benri (<span lang="ja" translate="no">便利</span>) means convenient</p>
          <h1 className={styles.title}>
            Your 10-minute radius shapes your life.
          </h1>
          <p className={styles.lead}>
            See what is around any address in the New York metro area, scored
            out of 100.
          </p>
          <HomeSearch />
          <Link className={styles.explore} href={APP_PATH} prefetch={false}>
            <svg
              className={styles.exploreIcon}
              viewBox="0 0 24 24"
              aria-hidden="true"
              focusable="false"
            >
              <path d="M9 4 3 6.5v13.5l6-2.5 6 2.5 6-2.5V4l-6 2.5zM9 4v13.5M15 6.5V20" />
            </svg>
            Explore the map
          </Link>
        </header>

        <section className={styles.section} aria-labelledby="what-you-get">
          <h2 id="what-you-get" className={styles.heading}>
            What you get
          </h2>
          <ul className={styles.benefits}>
            {BENEFITS.map((item) => (
              <li key={item.title} className={styles.benefit}>
                <h3 className={styles.benefitTitle}>{item.title}</h3>
                <p className={styles.benefitText}>{item.text}</p>
              </li>
            ))}
          </ul>
        </section>

        <section className={styles.section} aria-labelledby="what-we-score">
          <h2 id="what-we-score" className={styles.heading}>
            What we score
          </h2>
          {GROUP_ORDER.map((group) => (
            <div key={group} className={styles.group}>
              <h3 className={styles.groupName}>{FACTOR_GROUPS[group]}</h3>
              <ul className={styles.factors}>
                {FACTOR_GUIDE_ORDER.filter(
                  (key) => FACTORS[key].group === group,
                ).map((key) => (
                  <li key={key} className={styles.factor} data-factor={key}>
                    <FactorIcon
                      factor={key}
                      className={styles.icon}
                      aria-hidden="true"
                    />
                    <h4 className={styles.factorName}>{FACTORS[key].label}</h4>
                    <p className={styles.factorText}>{FACTOR_GUIDE[key].blurb}</p>
                  </li>
                ))}
              </ul>
            </div>
          ))}
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

        <section className={styles.section} aria-labelledby="coverage">
          <h2 id="coverage" className={styles.heading}>
            Coverage and data
          </h2>
          <div className={styles.notes}>
            <p className={styles.noteText}>
              <strong>New York metro.</strong> New York City and the surrounding
              parts of New York, New Jersey and Connecticut, within about two
              hours of the city.
            </p>
            <p className={styles.noteText}>
              <strong>Open data.</strong> Built from {DATA_SOURCES}. Scores are
              estimates, so check anything important in person.{" "}
              <Link href="/data">See every source and when it was updated.</Link>
            </p>
          </div>
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
