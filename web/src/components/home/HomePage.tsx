import Link from "next/link";

import { SiteFooter } from "@/components/SiteFooter";
import { FactorIcon } from "@/lib/factorIcons";
import { FACTOR_GUIDE_ORDER } from "@/lib/home/factorGuide";
import { scoreColor } from "@/lib/map/colors";
import { FACTORS, FACTOR_GROUPS, type FactorGroup } from "@/lib/score/factors";
import { APP_PATH } from "@/lib/site";

import {
  ExtraIcon,
  GroupIcon,
  NeighborhoodsIllustration,
  OptimizationDiagram,
  ReachIllustration,
  ScoreDiagram,
  ScoreIllustration,
  StopsIllustration,
  TriangulationDiagram,
} from "./Diagrams";
import { HeroSearch } from "./HeroSearch";
import styles from "./HomePage.module.css";

const STEPS = [
  {
    title: "Search",
    text: "Type an address in the New York metro area, or click the map.",
  },
  {
    title: "See the score",
    text: "One score out of 100, with a sub-score for every factor, in feet and miles.",
  },
  {
    title: "Make it yours",
    text: "Weight what matters, find similar areas or plan several stops at once.",
  },
] as const;

const FEATURES = [
  {
    title: "One score out of 100",
    text: "Built from the factors you pick, from groceries to transit and noise.",
    art: <ScoreIllustration />,
  },
  {
    title: "Real neighborhoods",
    text: "Areas bounded by real streets and named for the neighborhood, not squares.",
    art: <NeighborhoodsIllustration />,
  },
  {
    title: "Plan several stops",
    text: "Work, groceries, the gym: the optimizer ranks areas by total weekly travel.",
    art: <StopsIllustration />,
  },
  {
    title: "See how far you can get",
    text: "Walking, train or car: a travel-time area drawn right on the map.",
    art: <ReachIllustration />,
  },
] as const;

const EXTRAS = [
  { icon: "summary", title: "AI summary", text: "Plain words on what drives a score." },
  { icon: "similar", title: "Similar neighborhoods", text: "Find areas that feel alike." },
  { icon: "improve", title: "Improve this area", text: "See what would lift a score." },
] as const;

const GROUP_BLURB: Record<FactorGroup, string> = {
  amenities: "Food, coffee, fitness and shopping close to home.",
  mobility: "Trains, airports, gas and traffic for getting around.",
  neighborhood: "Schools, quiet streets and green space.",
};

const DIAGRAMS = [
  {
    key: "score",
    title: "How the score is built",
    text: "Each neighborhood counts what is inside it and what you can walk to nearby, with farther places counting less, all on one scale for the whole region. Groceries, gyms and gas count mostly by the nearest one; transit by the walk (or short drive) to a train station. 13 weighted factors become one score out of 100.",
    label:
      "Rings around a neighborhood fade with distance, and thirteen weighted factors flow into a dial reading 78 out of 100.",
    diagram: (label: string) => <ScoreDiagram label={label} />,
  },
  {
    key: "triangulate",
    title: "Triangulate between places",
    text: "Mark two or three places that matter, such as work, family and the gym. Each gets a travel-time area, and the best-scoring neighborhoods sit where they overlap. Times use real road and rail travel, not straight lines.",
    label:
      "Three travel-time areas for Work, Family and Gym overlap in the middle, where the best-scoring neighborhoods are marked.",
    diagram: (label: string) => <TriangulationDiagram label={label} />,
  },
  {
    key: "optimize",
    title: "Optimize your week",
    text: "Say how often you go to each place. Lines are weighted by trips per week, and the area with the lowest total weekly travel time that also scores well comes out on top.",
    label:
      "Work five times a week, groceries twice and the gym once connect to three candidate areas with lines weighted by trips; the most central area has the least weekly travel and wins.",
    diagram: (label: string) => <OptimizationDiagram label={label} />,
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
          <p className={styles.lead}>Find your neighborhood.</p>
          <HeroSearch />
        </header>

        <section className={styles.section} aria-labelledby="what-you-get">
          <h2 id="what-you-get" className={styles.heading}>
            What you get
          </h2>
          <ul className={styles.features}>
            {FEATURES.map((item) => (
              <li key={item.title} className={styles.feature}>
                <div className={styles.art}>{item.art}</div>
                <h3 className={styles.featureTitle}>{item.title}</h3>
                <p className={styles.featureText}>{item.text}</p>
              </li>
            ))}
          </ul>
          <ul className={styles.extras}>
            {EXTRAS.map((item) => (
              <li key={item.title} className={styles.extra}>
                <ExtraIcon name={item.icon} className={styles.extraIcon} />
                <div>
                  <h3 className={styles.extraTitle}>{item.title}</h3>
                  <p className={styles.extraText}>{item.text}</p>
                </div>
              </li>
            ))}
          </ul>
        </section>

        <section className={styles.section} aria-labelledby="what-we-score">
          <h2 id="what-we-score" className={styles.heading}>
            What we score
          </h2>
          <div className={styles.groups}>
            {GROUP_ORDER.map((group) => (
              <article key={group} className={styles.groupCard}>
                <GroupIcon group={group} className={styles.groupIcon} />
                <h3 className={styles.groupName}>{FACTOR_GROUPS[group]}</h3>
                <p className={styles.groupText}>{GROUP_BLURB[group]}</p>
                <ul className={styles.chips}>
                  {FACTOR_GUIDE_ORDER.filter(
                    (key) => FACTORS[key].group === group,
                  ).map((key) => (
                    <li key={key} className={styles.chip} data-factor={key}>
                      <FactorIcon
                        factor={key}
                        className={styles.chipIcon}
                        aria-hidden="true"
                      />
                      {FACTORS[key].label}
                    </li>
                  ))}
                </ul>
              </article>
            ))}
          </div>
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

          <h3 className={styles.subheading}>Behind the scenes</h3>
          <div className={styles.diagrams}>
            {DIAGRAMS.map((d) => (
              <figure key={d.key} className={styles.figure} data-diagram={d.key}>
                {d.diagram(d.label)}
                <figcaption className={styles.caption}>
                  <strong className={styles.captionTitle}>{d.title}</strong>
                  {d.text}
                </figcaption>
              </figure>
            ))}
          </div>
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
            See what&apos;s around you
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
