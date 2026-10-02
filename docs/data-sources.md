# Data sources: schools

Decision record for the school score (20% proximity, 80% rating).

**We link to GreatSchools; we do not ingest it.** GreatSchools ratings are
licensed data, their district-boundary map is not an API, and their terms
prohibit scraping. The UI may link out to greatschools.org; nothing from it is
fetched, stored or scored.

## Sources used

| Need | Source | Licence / terms |
|---|---|---|
| School locations (count, nearest) | NCES EDGE public school locations (2024-25), NY/NJ/CT | US federal government work; the NCES page states no licence text. Treated as public domain (verify at NCES before launch). Cite NCES. |
| District boundaries | Census TIGER/Line / NCES EDGE school district boundaries (unified, elementary, secondary) | Same federal-source data; public domain. |
| Ratings | EDFacts district assessment proficiency (math + reading, mean percent proficient) via the Urban Institute Education Data Portal | Portal text: "All data made available via the Education Data Portal in any form is licensed to you under the Open Data Commons Attribution License (ODC-By) v1.0." Commercial use allowed with attribution. |

Required attribution (UI footer / docs page):
"School ratings: EDFacts proficiency data, Education Data Portal (Urban
Institute), under ODC Attribution License. School and district locations: NCES.
Rating is a within-state percentile of state test proficiency, not a
GreatSchools rating."

## Rejected: Stanford SEDA

SEDA would give one national scale, but its Data Use Agreement says: "You agree
not to use the data sets for commercial advantage, or in the course of
for-profit activities" and "You agree not to publish the data files, in full or
in part, without explicit permission." Commercial entities must contact
Stanford's Office of Technology Licensing. Citation is also required
("Stanford Education Data Archive"). Serving district scores from a public
product may count as publishing in part, and a commercial future is planned, so
SEDA is not used. Revisit only with written permission.

## Method

1. Each cell centre is assigned to a district by point-in-polygon (STRtree).
   No match gives NULL, never the nearest district. Overlap priority:
   unified, then elementary, then secondary.
2. Raw rating = mean of math and reading percent proficient. Suppressed
   values (negative codes) are dropped; a district with none stays NULL.
3. Because each state has its own test, raw values are not comparable across
   NY/NJ/CT. Ratings are converted to a 0-100 mid-rank percentile within each
   state before writing, so the engine's per-metro min-max cohort is comparable.
4. Written to `school_district_rating` (and mirrored in
   `school_avg_rating_1600m`, the column the engine reads), with
   `school_district_geoid`, `school_district_name` and `school_rating_source`.
   An unrated cell gets a NULL school score.

Caveats: district-level only (no within-district variation); proficiency
reflects student demographics as well as school quality; the EDFacts year is
older than today.
