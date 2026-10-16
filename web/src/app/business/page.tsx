import type { Metadata } from "next";
import Link from "next/link";

import { InfoPage } from "@/components/InfoPage";
import styles from "@/components/InfoPage.module.css";

export const metadata: Metadata = { title: "For Business · BenriSpace" };

const SEGMENTS = [
  {
    id: "listings",
    title: "Listing platforms and brokerages",
    text: "Show a convenience score and its 13 factors on every listing, and give clients an area report for any address in the New York metro.",
  },
  {
    id: "relocation",
    title: "Relocation and HR",
    text: "Given where an employee works, where the kids go to school and the places they visit weekly, rank the areas that fit best by total travel time.",
  },
  {
    id: "multifamily",
    title: "Multifamily owners and marketers",
    text: "Back up building marketing with measured walk and drive times to groceries, transit, gyms and parks.",
  },
  {
    id: "site-selection",
    title: "Retail site selection",
    text: "Find areas where people live but a category such as groceries or gyms is missing nearby. In development.",
  },
] as const;

export default function BusinessPage() {
  return (
    <InfoPage
      title="For Business"
      lead="Convenience and travel-time scores for every road-bounded area in NY, NJ and CT, on one scale, ready to use in your product."
    >
      {SEGMENTS.map(({ id, title, text }) => (
        <section key={id} id={id} className={styles.card} aria-labelledby={`${id}-heading`}>
          <h2 id={`${id}-heading`}>{title}</h2>
          <p>{text}</p>
        </section>
      ))}
      <section className={styles.card} aria-labelledby="start-heading">
        <h2 id="start-heading">Get started</h2>
        <p>
          The <Link href="/docs#api">API</Link> is open to try today with no key. Volume
          licensing is on the <Link href="/pricing">Business plan</Link>.
        </p>
        <span className={styles.soon}>Business accounts coming with paid plans</span>
      </section>
    </InfoPage>
  );
}
