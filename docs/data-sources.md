# Data sources

Where each input comes from, its licence, and the decisions behind it. The school score
(20% proximity, 80% rating) comes first because it had the most licensing questions.

**We link to GreatSchools; we do not ingest it.** GreatSchools ratings are
licensed data, their district-boundary map is not an API, and their terms
prohibit scraping. The UI may link out to greatschools.org; nothing from it is
fetched, stored or scored.

## Sources used

| Need | Source | Licence / terms |
|---|---|---|
| School locations (count, nearest) | NCES EDGE public school locations (2024-25), NY/NJ/CT | US federal government work; the NCES page states no licence text. Treated as public domain (verify at NCES before launch). Cite NCES. |
| District boundaries | Census TIGER/Line / NCES EDGE school district boundaries (unified, elementary, secondary) | Same federal-source data; public domain. |
| Ratings | EDFacts district assessment proficiency (math + reading, mean percent proficient), school year 2018, via the Urban Institute Education Data Portal (`/api/v1/school-districts/edfacts/assessments/2018/grade-99/`, grade 99 = all grades) | Portal text: "All data made available via the Education Data Portal in any form is licensed to you under the Open Data Commons Attribution License (ODC-By) v1.0." Commercial use allowed with attribution. |

**Why 2018.** The portal's EDFacts district assessments cover 2009-2018 and 2020; there is no 2019 file, and 2020 is skipped because testing was waived that spring. 2018 is the latest full year. The endpoint was checked live on 2026-10-02 and returns 1,637 districts across the three states (NY 785, NJ 652, CT 200).

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
   `school_avg_rating_1mi`, the column the engine reads (called `school_avg_rating_1600m` before migration 0020)), with
   `school_district_geoid`, `school_district_name` and `school_rating_source`.
   An unrated cell gets a NULL school score.

Where this appears: the website footer credits NCES and the Education Data Portal (Urban Institute, ODC Attribution License). Cells whose district has no rating show the school score as "No data", with proximity shown separately.

Caveats: district-level only (no within-district variation); proficiency
reflects student demographics as well as school quality; the EDFacts year is
older than today (2018 data); NJ and CT use different state tests from NY, which is why ratings are converted to within-state percentiles.

## Shopping and parks (v2.1, `osm_retail_parks`)

OpenStreetMap via Overpass, one query per metro bbox (quadrant-split on timeout), `out center bb tags`. ODbL, attribute OpenStreetMap contributors. In production (migration `0009_v2_1.sql`), refreshed by the weekly ingestion.

- **Shopping:** `shop=` department_store, mall, clothes, shoes, boutique, fashion_accessories, bag, jewelry, watches, doityourself, hardware, furniture, interior_decoration, houseware, bed, kitchen, garden_centre, electronics, computer, mobile_phone, chemist, beauty, cosmetics, perfumery, variety_store, general, gift, books, sports, toys, stationery, art, music, outdoor. Groceries and convenience stores are separate factors. Columns: `shopping_count_1mi`, `shopping_nearest_ft`, `shopping_variety_count_1mi` (distinct retail groups within 1 mi), `shopping_raw`.
- **Parks:** `leisure=park|playground|nature_reserve|garden` and `landuse=recreation_ground`, excluding `access=private|no`. Area is estimated from the element's bounding box (x 0.65), so it is approximate. Columns: `park_count_1mi`, `park_nearest_ft`, `park_largest_sq_ft_half_mi`, `recreation_raw`.
- Named shops and parks are written to `places` (categories `shopping`, `park`; sources `osm_retail` and `osm_parks`, separate from the `osm` POI rows).

## Transit coverage (GTFS + OSM)

| Source | Status | Notes |
|---|---|---|
| MTA, LIRR, Metro-North | GTFS static zips (rrgtfsfeeds.s3.amazonaws.com) | Public. |
| PATH | GTFS zip `https://data.trilliumtransit.com/gtfs/path-nj-us/path-nj-us.zip` | Public; verified 2026-10-03 (HTTP 200, zip with stops.txt). |
| OpenStreetMap transit stops (`osm_transit`, agency `osm`) | Overpass, one query per metro bbox | Nodes tagged railway=station/halt/tram_stop, public_transport=station, highway=bus_stop with a name or ref (no subway entrances). ODbL, attribute OpenStreetMap contributors. OSM stops within 40 m of a GTFS stop, or same-named within 40 m of each other, are dropped so counts are not inflated. Named stops go to `places` as source `osmtransit` (separate from `osm` POIs). If Overpass fails, the run continues with GTFS only. Fills NJ Transit, CT, Westchester and Long Island bus gaps. |
| NJ Transit (`gtfs_nj_transit`) | Open official feeds, no key: https://www.njtransit.com/rail_data.zip and https://www.njtransit.com/bus_data.zip (verified 2026-10-04; Mobility Database mdb-509 rail, mdb-508 bus) | OSM transit stops still fill remaining gaps. |

## Neighborhood names (`neighborhoods`)

Labels such as "Park Slope, Brooklyn", "Montclair, NJ" or "Newtown, CT" for every grid cell and road-bounded area (`neighborhood` columns, migration 0008). Town boundaries come from Census TIGER/Line county subdivisions (public domain): https://www2.census.gov/geo/tiger/TIGER2024/COUSUB/tl_2024_{36,34,09}_cousub.zip (NY, NJ, CT; verified 2026-10-04), cached under `data/cache/cousub/`. Neighbourhood names come from OpenStreetMap `place=neighbourhood|suburb|quarter` nodes via Overpass (one query per metro bbox; ODbL, attribute OpenStreetMap contributors), each filed under the town polygon that contains it.

- Inside New York City: "Neighbourhood, Borough" (nearest node within 1.2 mi in the same borough, borough from the county: Bronx, Brooklyn, Manhattan, Queens, Staten Island); otherwise just the borough.
- Inside a town with at least 5 neighbourhood nodes (Jersey City, Newark, Stamford, ...): "Neighbourhood, City" from nodes inside that town within 1.2 mi; otherwise "City, ST".
- Anywhere else: "Town, ST" with legal suffix words (town, township, city, village, borough) dropped. A label never uses a place outside the containing town, so it cannot cross a river or state line.
- Points in no town polygon (water, edge) use the nearest town within 0.5 mi, else no label. Coordinates are never used as a label.

## Population density and travel mode (`density`, Wave 3)

| Source | Notes |
|---|---|
| 2020 Census PL 94-171 redistricting files, NY / NJ / CT (`www2.census.gov/programs-surveys/decennial/2020/data/01-Redistricting_File--PL_94-171/`) | Block-group (summary level 150) total population `P0010001` and `AREALAND`. Used instead of `api.census.gov`, which now rejects keyless requests (302 to `missing_key`). About 117 MB, cached in `data/cache/density/`. Public domain (US federal). |
| TIGER/Line 2020 block groups (`www2.census.gov/geo/tiger/TIGER2020/BG/tl_2020_{fips}_bg.zip`) | Polygons. Public domain. |

Density = population / land square miles per block group, area-weighted to each cell's geohash
rectangle (shapely STRtree, exact intersection). `travel_mode` = `drive` below 10,000 people / sq mi,
else `walk`. Cells with no block group (open water, the Pennsylvania part of the NJ box) stay NULL.
First run on real data (64,320 cells): 71.8% drive, 3.2% walk, 25.1% NULL (mostly water). Samples:
Manhattan Midtown 28,507 walk; Upper West Side 129,936; Park Slope 69,259; Hoboken 50,281; Jersey City
68,279; Yonkers 33,498 (all walk); Montclair 5,168 drive; White Plains 18,156 and Stamford 16,410
walk (above the 10k line); Huntington 3,991 drive; rural Fairfield County CT 212-988 drive.

## Major roads and rail (`road_segments`, Wave 3)

OpenStreetMap via Overpass (ODbL): `highway` motorway..secondary plus links, and `railway=rail`,
stored whole per way in `road_segments` (PostGIS LineString) with `is_emergency_route` set for
secondary and above. Feeds later noise-by-frontage work; nothing reads it yet, so it is not loaded
weekly and the production table is empty. Run `python -m ingestion.road_segments` by hand
when the frontage-noise factor needs it.

## Road networks and train times (routing, Wave 4)

| Source | Notes |
|---|---|
| Geofabrik OpenStreetMap extracts for New York, New Jersey and Connecticut (`download.geofabrik.de/north-america/us/<state>-latest.osm.pbf`) | ODbL, attribute OpenStreetMap contributors. Saved in `build/osm/` (about 840 MB) and turned into walk, drive and arterial networks by `ingestion.routing.pbf`. Replaces Overpass for routing because public Overpass rate-limits bulk downloads. Refreshed by hand, about monthly. |
| GTFS rail feeds (subway, LIRR, Metro-North, PATH, NJ Transit rail), the same feeds as `gtfs_transit` | Weekday morning-peak ride times between 933 stations (`rail_matrix`), by the Connection Scan Algorithm. |

Routed minutes, place tallies and densities are internal scoring inputs and are never shown to
users.
