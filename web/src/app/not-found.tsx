import Link from "next/link";

import { SiteFooter } from "@/components/SiteFooter";

import styles from "./not-found.module.css";

export default function NotFound() {
  return (
    <>
      <main id="main" className={styles.main}>
        <h1 className={styles.title}>Page not found</h1>
        <p className={styles.body}>
          There&rsquo;s nothing at this address on BenriSpace.
        </p>
        <Link href="/">Score an address</Link>
      </main>
      <SiteFooter />
    </>
  );
}
