import type { Metadata } from "next";

import { InfoPage } from "@/components/InfoPage";
import styles from "@/components/InfoPage.module.css";

export const metadata: Metadata = { title: "Login · BenriSpace" };

export default function LoginPage() {
  return (
    <InfoPage
      title="Login"
      lead="Accounts are planned for a later phase, starting with Google sign-in. You do not need one to use BenriSpace today."
    >
      <section className={styles.card}>
        <h2>Sign in with Google</h2>
        <span className={styles.soon}>Coming soon</span>
      </section>
    </InfoPage>
  );
}
