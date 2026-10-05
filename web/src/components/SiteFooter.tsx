import Link from "next/link";

import styles from "./SiteFooter.module.css";

function ExternalLink({ href, children }: { href: string; children: string }) {
  return (
    <a href={href} target="_blank" rel="noreferrer">
      {children}
    </a>
  );
}

/**
 * OpenStreetMap data requires attribution wherever it is used. Scores, the
 * basemap and address search all derive from it, so every page credits it.
 */
export function SiteFooter() {
  return (
    <footer className={styles.footer}>
      <p>
        Map data ©{" "}
        <ExternalLink href="https://www.openstreetmap.org/copyright">
          OpenStreetMap contributors
        </ExternalLink>{" "}
        (
        <ExternalLink href="https://opendatacommons.org/licenses/odbl/">
          ODbL
        </ExternalLink>
        ). Basemap by{" "}
        <ExternalLink href="https://openfreemap.org">OpenFreeMap</ExternalLink>{" "}
        ©{" "}
        <ExternalLink href="https://openmaptiles.org">
          OpenMapTiles
        </ExternalLink>
        . Address search by{" "}
        <ExternalLink href="https://locationiq.com">LocationIQ</ExternalLink>,{" "}
        <ExternalLink href="https://photon.komoot.io">Photon</ExternalLink> and{" "}
        <ExternalLink href="https://nominatim.org">Nominatim</ExternalLink>{" "}
        (OSM). Also{" "}
        <ExternalLink href="https://opendata.cityofnewyork.us">
          NYC Open Data
        </ExternalLink>
        ,{" "}
        <ExternalLink href="https://www.mta.info/developers">MTA</ExternalLink>{" "}
        and{" "}
        <ExternalLink href="https://developer.njtransit.com">
          NJ Transit
        </ExternalLink>{" "}
        GTFS. School locations from{" "}
        <ExternalLink href="https://nces.ed.gov/programs/edge/">NCES</ExternalLink>{" "}
        and district ratings from the{" "}
        <ExternalLink href="https://educationdata.urban.org/">
          Education Data Portal
        </ExternalLink>{" "}
        (Urban Institute, ODC Attribution License). Scores describe an area,
        not a single building. See all{" "}
        <Link href="/data">data sources and licences</Link>.
      </p>
    </footer>
  );
}
