"use client";

import Link from "next/link";
import { useState } from "react";

import styles from "./PricingTiers.module.css";

type Billing = "monthly" | "yearly";

interface Tier {
  name: string;
  blurb: string;
  features: string[];
  cta: string;
  href: string;
  featured?: boolean;
}

const TIERS: Tier[] = [
  {
    name: "Free",
    blurb: "Score addresses and explore the map.",
    features: [
      "Address scores on 13 factors",
      "Interactive map",
      "Best areas for your priorities",
      "Ask Benri chat, 15 messages a day",
    ],
    cta: "Start for free",
    href: "/app",
  },
  {
    name: "Pro",
    blurb: "For people comparing places to live.",
    features: [
      "Everything in Free",
      "Points of interest travel-time overlap",
      "Compare places side by side",
      "Similar areas",
      "Higher daily Ask Benri limit",
    ],
    cta: "Choose Pro",
    href: "/login",
    featured: true,
  },
  {
    name: "Business",
    blurb: "For teams and API access at volume.",
    features: [
      "Everything in Pro",
      "API and MCP access",
      "Bulk scoring",
      "Priority support",
    ],
    cta: "Contact us",
    href: "/login",
  },
];

// Placeholder prices: not final.
const PRO_PRICE = { monthly: "$9", yearly: "$90" } as const;

/** The three plan cards with a monthly or yearly switch for Pro. */
export function PricingTiers() {
  const [billing, setBilling] = useState<Billing>("monthly");

  return (
    <div>
      <div className={styles.toggle} role="group" aria-label="Billing period">
        {(["monthly", "yearly"] as const).map((value) => (
          <button
            key={value}
            type="button"
            aria-pressed={billing === value}
            className={styles.toggleButton}
            onClick={() => setBilling(value)}
          >
            {value === "monthly" ? "Monthly" : "Yearly"}
          </button>
        ))}
      </div>
      <div className={styles.tiers}>
        {TIERS.map((tier) => (
          <section
            key={tier.name}
            className={
              tier.featured ? `${styles.card} ${styles.featured}` : styles.card
            }
            aria-labelledby={`tier-${tier.name}`}
          >
            {tier.featured ? (
              <span className={styles.badge}>Recommended</span>
            ) : null}
            <h2 id={`tier-${tier.name}`}>{tier.name}</h2>
            <p className={styles.blurb}>{tier.blurb}</p>
            <p className={styles.price}>
              {tier.name === "Free" ? (
                "$0"
              ) : tier.name === "Pro" ? (
                <>
                  {PRO_PRICE[billing]}
                  <span className={styles.per}>
                    {billing === "monthly" ? " / month" : " / year"}
                  </span>
                </>
              ) : (
                "Contact us"
              )}
            </p>
            <p className={styles.placeholder}>
              {tier.name === "Pro"
                ? "Placeholder price"
                : tier.name === "Free"
                  ? "Free"
                  : "Custom pricing"}
            </p>
            <ul className={styles.features}>
              {tier.features.map((feature) => (
                <li key={feature}>{feature}</li>
              ))}
            </ul>
            <Link
              href={tier.href}
              className={
                tier.featured
                  ? `${styles.cta} ${styles.ctaPrimary}`
                  : styles.cta
              }
            >
              {tier.cta}
            </Link>
          </section>
        ))}
      </div>
    </div>
  );
}
