import Link from "next/link";

import type { FactorKey } from "@/lib/api/types";
import { SiteFooter } from "@/components/SiteFooter";
import {
  FACTOR_GUIDE,
  FACTOR_GUIDE_ORDER,
  MAX_FACTOR_WEIGHT,
  UNDERLYING_GUIDE_ORDER,
} from "@/lib/home/factorGuide";
import { RAMP_GRADIENT } from "@/lib/map/colors";
import { PRESETS } from "@/lib/map/selection";
import { FACTORS, FACTOR_GROUPS } from "@/lib/score/factors";
import { APP_PATH, EXAMPLE_ADDRESSES } from "@/lib/site";

import styles from "./HomePage.module.css";

const STEPS = [
  {
    title: "Search or click",
    text: "Type an address in the New York metro area, or click anywhere on the map.",
  },
  {
    title: "Get a score out of 100",
    text: "You see an overall score and a sub-score for each factor, with a plain-language explanation.",
  },
  {
    title: "Read the colored map",
    text: "Every area of the map is colored by how well it scores on the factors you pick.",
  },
  {
    title: "Find the best areas",
    text: "A ranked list shows the strongest, well-separated spots for those factors.",
  },
] as const;

const BUILD_POINTS = [
  {
    title: "Precomputed",
    text: "Scores are calculated ahead of time in a batch and refreshed weekly, so looking one up is instant.",
  },
  {
    title: "Relative, not absolute",
    text: "Each factor is scaled from 0 to 100 across the cells of the same part of the metro area (for example Long Island, or northern New Jersey). 100 means best there, and 0 means worst there. A suburban street is compared with other suburban streets, not with Midtown.",
  },
  {
    title: "A weighted average",
    text: "The overall score averages the factor scores, and some factors count for more than others (see the weights below). On the map you can choose which factors count and how much.",
  },
  {
    title: "Missing data is left out",
    text: "If a factor has no data for a spot, it is skipped (stored as null) and the average is taken over the rest. It is never counted as a zero. Schools follow the same rule: where no district rating exists we say so and show proximity alone.",
  },
  {
    title: "Schools: 20% proximity, 80% rating",
    text: "The school sub-score is 20% how close and how many schools are nearby, and 80% the district rating. GreatSchools is linked from the score card for further reading, but it is not used as a data source.",
  },
  {
    title: "No spot is perfect",
    text: "Factors pull against each other. The places with the best transit, cafes and groceries are dense, and dense places have more gas stations, traffic and sirens. Nowhere scores 100 on everything, so an overall score near 80 is exceptional.",
  },
] as const;

const SOURCES = [
  {
    name: "OpenStreetMap",
    href: "https://www.openstreetmap.org/copyright",
    text: "shops, gyms, cafes, restaurants, bars and pubs, Whole Foods, Starbucks and Target, fire stations, hospitals and police stations, roads and running trails, plus the basemap",
  },
  {
    name: "MTA, LIRR, Metro-North and NJ Transit",
    href: "https://www.mta.info/developers",
    text: "transit stops from their published schedule (GTFS) feeds",
  },
  {
    name: "NCES",
    href: "https://nces.ed.gov/programs/edge/",
    text: "public school and school district locations across New York, New Jersey and Connecticut",
  },
  {
    name: "Education Data Portal (Urban Institute)",
    href: "https://educationdata.urban.org/",
    text: "district test proficiency from EDFacts, used under the ODC Attribution License",
  },
] as const;

function Actions() {
  return (
    <div className={styles.actions}>
      <Link className={styles.primary} href={APP_PATH} prefetch={false}>
        Open the app
      </Link>
      <Link className={styles.secondary} href="/docs" prefetch={false}>
        See the API
      </Link>
    </div>
  );
}

function FactorCard({ factorKey: key }: { factorKey: FactorKey }) {
  const meta = FACTORS[key];
  const entry = FACTOR_GUIDE[key];
  const negative = entry.direction !== "closer";
  return (
    <li className={styles.factor} data-factor={key}>
      <h3 className={styles.factorName}>{meta.label}</h3>
      <p className={styles.factorTags}>
        <span>{entry.underlying ? "Behind the scenes" : FACTOR_GROUPS[meta.group]}</span>
        {negative ? (
          <span className={styles.negative}>Counts against a place</span>
        ) : null}
      </p>
      <p>
        <strong>Measures:</strong> {entry.measures}
      </p>
      <p>
        <strong>What is better:</strong> {entry.better} {entry.why}
      </p>
      <p className={styles.weight}>
        <span>
          <strong>Weight:</strong> {entry.weight}
        </span>
        <span className={styles.weightTrack} aria-hidden="true">
          <span
            className={styles.weightFill}
            style={{ width: `${(entry.weight / MAX_FACTOR_WEIGHT) * 100}%` }}
          />
        </span>
      </p>
      <p className={styles.caveat}>
        <strong>Keep in mind:</strong> {entry.caveat}
      </p>
    </li>
  );
}

/** The static landing page: what BenriSpace is and how its scores work. */
export function HomePage() {
  return (
    <>
      <main id="main" className={styles.main}>
        <header className={styles.hero}>
          <p className={styles.eyebrow}>Benri (便利) means convenient</p>
          <h1 className={styles.title}>How convenient is that address?</h1>
          <p className={styles.lead}>
            Search for an address in the New York metro area, or click anywhere
            on the map, to see a score out of 100 for groceries, transit,
            schools, running routes and more. The map colors show where the factors you
            pick score best.
          </p>
          <Actions />
          <p className={styles.tryRow}>
            <span className={styles.tryLabel}>Try</span>
            {EXAMPLE_ADDRESSES.map((address) => (
              <Link
                key={address}
                className={styles.example}
                href={`${APP_PATH}?${new URLSearchParams({ address })}`}
                prefetch={false}
              >
                {address}
              </Link>
            ))}
          </p>
        </header>

        <section className={styles.section} aria-labelledby="how-it-works">
          <h2 id="how-it-works" className={styles.heading}>
            How it works
          </h2>
          <ol className={styles.steps}>
            {STEPS.map((step) => (
              <li key={step.title} className={styles.step}>
                <h3 className={styles.stepTitle}>{step.title}</h3>
                <p>{step.text}</p>
              </li>
            ))}
          </ol>
        </section>

        <section className={styles.section} aria-labelledby="how-built">
          <h2 id="how-built" className={styles.heading}>
            How a score is built
          </h2>
          <p className={styles.intro}>
            Twelve factors each get their own score from 0 to 100, where higher
            is always better. Two behind-the-scenes signals are scored the same way. Factors where less is better, such as gas
            stations or traffic, are flipped first, so a high gas station score
            means few of them nearby.
          </p>
          <dl className={styles.points}>
            {BUILD_POINTS.map((point) => (
              <div key={point.title} className={styles.point}>
                <dt>{point.title}</dt>
                <dd>{point.text}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section className={styles.section} aria-labelledby="factors">
          <h2 id="factors" className={styles.heading}>
            The twelve factors
          </h2>
          <p className={styles.intro}>
            Distances are in feet and miles. Weight is how much a factor counts
            in the overall score by default; the highest weight is{" "}
            {MAX_FACTOR_WEIGHT}.
          </p>
          <ul className={styles.factors}>
            {FACTOR_GUIDE_ORDER.map((key) => (
              <FactorCard key={key} factorKey={key} />
            ))}
          </ul>
        </section>

        <section className={styles.section} aria-labelledby="underlying">
          <h2 id="underlying" className={styles.heading}>
            Behind-the-scenes signals
          </h2>
          <p className={styles.intro}>
            Two more metrics count toward the overall score but are not on the
            factor list, so you cannot switch them off. They are left out of the
            score when you pick specific factors on the map.
          </p>
          <ul className={styles.factors}>
            {UNDERLYING_GUIDE_ORDER.map((key) => (
              <FactorCard key={key} factorKey={key} />
            ))}
          </ul>
        </section>

        <section className={styles.section} aria-labelledby="reading-map">
          <h2 id="reading-map" className={styles.heading}>
            Reading the map
          </h2>
          <div
            className={styles.legend}
            style={{ background: RAMP_GRADIENT }}
            role="img"
            aria-label="Color scale from dark purple for low scores to yellow for high scores"
          />
          <div className={styles.legendScale} aria-hidden="true">
            <span>0 (lowest)</span>
            <span>100 (highest)</span>
          </div>
          <ul className={styles.list}>
            <li>
              <strong>Colors.</strong> The map uses the viridis scale: dark
              purple for low scores, through green, to bright yellow for high
              ones. The legend also shows the range of scores in view.
            </li>
            <li>
              <strong>Factor toggles.</strong> Tick only the factors you care
              about and the map recolors using just those. Pick a single factor
              to see where it is at its best.
            </li>
            <li>
              <strong>Presets.</strong> One-click sets of factors:{" "}
              {PRESETS.map((preset, index) => (
                <span key={preset.id}>
                  {index > 0 ? "; " : ""}
                  {preset.label} (
                  {preset.description.replace(/\.$/, "").toLowerCase()})
                </span>
              ))}
              .
            </li>
            <li>
              <strong>Importance sliders.</strong> Set any factor to Low (half
              its usual weight), Normal or High (double) to match what matters
              to you.
            </li>
            <li>
              <strong>Best areas.</strong> A ranked list of the strongest,
              well-separated areas for the factors you chose. Click one to score
              that spot.
            </li>
          </ul>
        </section>

        <section className={styles.section} aria-labelledby="sources">
          <h2 id="sources" className={styles.heading}>
            Data sources and limits
          </h2>
          <ul className={styles.list}>
            {SOURCES.map((source) => (
              <li key={source.name}>
                <a href={source.href} target="_blank" rel="noreferrer">
                  {source.name}
                </a>
                : {source.text}.
              </li>
            ))}
          </ul>
          <ul className={styles.list}>
            <li>
              <strong>School ratings.</strong> The rating is a district&rsquo;s
              state test proficiency, shown as a percentile within its own
              state, so it is not a GreatSchools rating and says little about
              any one school. GreatSchools is linked, not used as a data
              source: none of its data is copied into BenriSpace.
            </li>
            <li>
              <strong>Coverage.</strong> New York City, Long Island,
              Westchester, the Hudson Valley, northern New Jersey and Fairfield
              County, Connecticut.
            </li>
            <li>
              <strong>Resolution.</strong> The metro area is split into cells
              about 0.75 mi by 0.4 mi, so a score describes an area, not a
              single building.
            </li>
            <li>
              <strong>Open data has gaps.</strong> OpenStreetMap is edited by
              volunteers and is more complete in some neighborhoods than others.
              Several factors are rough proxies, as noted on each card above.
            </li>
            <li>
              <strong>Not advice.</strong> BenriSpace is a guide for exploring
              places. It is not financial, real-estate or safety advice, so
              check any place in person before you decide.
            </li>
          </ul>
        </section>

        <section className={styles.closing} aria-labelledby="start">
          <h2 id="start" className={styles.heading}>
            Ready to try it?
          </h2>
          <Actions />
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
