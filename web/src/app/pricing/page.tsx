import type { Metadata } from "next";

import { InfoPage } from "@/components/InfoPage";
import styles from "@/components/InfoPage.module.css";

export const metadata: Metadata = { title: "Pricing · BenriSpace" };

const TIERS = [
  { name: "Free", blurb: "Score addresses and explore the map." },
  { name: "Pro", blurb: "For people comparing places to live." },
  { name: "Business", blurb: "For teams and API access at volume." },
] as const;

export default function PricingPage() {
  return (
    <InfoPage
      title="Pricing"
      lead="BenriSpace is free while it is being built. Paid plans are planned for a later phase; nothing here is final."
    >
      <div className={styles.tiers}>
        {TIERS.map((tier) => (
          <section key={tier.name} className={styles.card}>
            <h2>{tier.name}</h2>
            <p>{tier.blurb}</p>
            <span className={styles.soon}>Coming soon</span>
          </section>
        ))}
      </div>
    </InfoPage>
  );
}
