import styles from "./PricingFaq.module.css";

const FAQ = [
  {
    q: "Is BenriSpace free right now?",
    a: "Yes. BenriSpace is free while it is in beta, and prices on this page are not final.",
  },
  {
    q: "What counts toward the Ask Benri limit?",
    a: "Each message you send to Ask Benri counts once. The Free plan allows 15 messages a day, and the limit resets daily.",
  },
  {
    q: "Do I need an account to use the app?",
    a: "Not today. Accounts are coming soon, and you can score addresses without signing in.",
  },
  {
    q: "How do I get API or MCP access?",
    a: "Those are planned for the Business plan. Contact us if you need them sooner.",
  },
] as const;

/** Short questions and answers under the plan cards. */
export function PricingFaq() {
  return (
    <section className={styles.faq} aria-labelledby="faq-heading">
      <h2 id="faq-heading">Questions</h2>
      {FAQ.map((item) => (
        <details key={item.q} className={styles.item}>
          <summary>{item.q}</summary>
          <p>{item.a}</p>
        </details>
      ))}
    </section>
  );
}
