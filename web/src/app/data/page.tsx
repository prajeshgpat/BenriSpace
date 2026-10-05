import type { Metadata } from "next";

import { DataSources } from "@/components/DataSources";
import { InfoPage } from "@/components/InfoPage";
import styles from "@/components/InfoPage.module.css";

export const metadata: Metadata = { title: "Data sources · BenriSpace" };

export default function DataPage() {
  return (
    <InfoPage
      title="Data sources"
      lead="Where every score comes from, under which licence, and when it was last refreshed."
    >
      <section className={styles.card}>
        <DataSources />
      </section>
    </InfoPage>
  );
}
