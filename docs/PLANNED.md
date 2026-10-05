# BenriSpace — Planned Work

Everything planned but not shipped, in one place. [ROADMAP.md](ROADMAP.md) records goals,
what is done and the decisions log; this file is the backlog to pull from. Each item says
**why**, **how** and **what it depends on**. Status markers: `[ ]` planned,
`[~]` in progress, `[x]` done (move done items to ROADMAP.md).

Last updated 2026-10-04.

---

## Wave 1 — Quick performance wins

Low-risk changes to the database and API that make every request faster.

- [~] **Spatial index on cells.** `geo_entities (latitude, longitude)` btree. Bounding-box
  queries (map cells, improve, optimize candidates) stop scanning all 64k rows.
- [~] **Similar areas use the vector index.** Fetch the target vector first, then
  `ORDER BY embedding <-> $vector LIMIT k` with a weights-version filter, so pgvector's
  HNSW index is used instead of a join that scans every row.
- [~] **Precomputed similar neighbours.** Top 20 similar cells per cell, written by the
  embeddings step into a `similar_cells` table; `/v1/similar` becomes a lookup plus the
  selected-factor re-rank.
- [~] **Trigram search on places.** `pg_trgm` GIN index on `places.name` / `brand`, so
  brand matching ("trader joe") is indexed.
- [~] **Covering index (view skipped: measured no win).** `scores (weights_version, geo_entity_id)`
  covering index; a materialized view of the latest scores joined to cells for map and top
  queries (refreshed by the scoring job).
- [ ] **Edge caching.** Cloudflare cache rules for GET endpoints that already send
  `Cache-Control` (map, area, score, places, similar, improve).
- [~] **Faster cold starts.** Import the Anthropic SDK, shapely and routing clients lazily;
  measure; consider Lambda SnapStart (a few cents a month).
- [~] **Lambda timeout 20 s → 29 s** so multi-tool chat answers fit (API Gateway caps at 30 s).
- [~] **Chat grounding tuned.** Allow numbers that are sums / roundings of tool values and
  names that appear in tool results, so fewer good answers fall back to the plain summary.

## Wave 2 — Instant filters in the browser

- [~] **Compact score file.** One file per weights version with each cell's 13 sub-scores
  as bytes (64k × 13 ≈ 0.8 MB, ≈ 300 KB compressed), served with long cache headers and a
  version tag. The overall score is a weighted average, so the browser recomputes it
  exactly for any filter or importance change: the map recolours instantly with no API
  call.
- [ ] **Best areas computed locally.** k-best selection with a heap (O(n log k)) plus a grid
  hash for the 1-mile spacing (O(n)), replacing the widening SQL loop.
- [ ] **Vector tiles.** PMTiles (tippecanoe, Docker) for the cell grid and neighbourhood
  polygons, served from a CDN bucket (Cloudflare R2 recommended: free tier, no egress),
  joined to the score file by id. Pans and zooms stop calling the API.

## Wave 3 — Data foundation for scoring v3

- [ ] **Imperial column rename.** `*_count_500m` → `*_count_1600ft`, `*_nearest_m` →
  `*_nearest_ft` (values × 3.2808), `*_1600m` → `*_1mi`, `area_sq_m` → `area_sq_mi`, via
  expand (add + backfill) → deploy → contract (drop) migrations.
- [~] **Population density per cell.** 2020 Census block-group population and land area,
  area-weighted to cells; travel mode = car below 10,000 people / sq mi, walk + transit at
  or above. Built: `ingestion/density.py` (Census PL files, no key), migration 0012 not applied.
- [~] **PostGIS.** Geometry columns and GiST indexes on `areas`, `places`, `geo_entities`
  and a new `road_segments` (major roads, rail) table. Polygon lookup (`ST_Contains`),
  nearby places (KNN `<->`) and noise distances become indexed spatial queries.
- [~] **Faster ingestion.** `scipy.spatial.cKDTree` + numpy for nearest / within-radius
  counts (10–100× faster than Python bucket scans); run non-Overpass jobs in parallel. Built
  for `osm_poi`, shops in `osm_retail_parks` and `gtfs_transit` (`ingestion/spatial.py`); parks
  (rectangles) and schools (3x3-bucket semantics) still use bucket scans.

## Wave 4 — Routing precompute

- [~] **Walk / drive minutes per cell.** One multi-source network search per amenity
  category (Pandana k-nearest over a contraction-hierarchy network) instead of 64,000
  point-to-point queries; nearest and k-th nearest minutes for every cell. Prototype:
  `scripts/routing_prototype.py` (Park Slope: 9.9k nodes, k=3 search 0.05 s).
- [ ] **Drive matrices** to airports and rail stations (OSRM table service, contraction
  hierarchies), or Valhalla where isochrones are needed.
- [ ] **Train times.** Station-to-station matrix for every rail station (r5py / RAPTOR) from
  the GTFS already ingested (MTA, LIRR, Metro-North, PATH, NJ Transit). Any address's train
  trip = walk to nearby stations + precomputed ride + walk.
- [ ] **Optimizer upgrades.** Seed the search at the weighted geometric median of the anchors
  (Weiszfeld's algorithm), prune candidates whose straight-line lower bound cannot win, and
  use the precomputed train times instead of estimates.
- [ ] **Real `/triangulate`.** Isochrones from 2–4 anchors, intersected / unioned, then rank
  the precomputed scores inside (replaces the circle placeholder).

## Wave 5 — Scoring v3 (`v3-timeaccess`) and cutover

- [ ] Per-factor time curves by travel mode ([SCORING.md](SCORING.md) Part B, 1.2).
- [ ] Travel mode by density class (car below 10k / sq mi).
- [ ] Dining density inside the neighbourhood polygon + a 10-minute walk.
- [ ] Transit service quality from GTFS frequencies (routes, rail vs bus, peak headways).
- [ ] Noise by frontage band from road geometry (frontage 100 %, behind first row 35 %,
  interior 10 %); highways and rail with a wider fade; gas / convenience adjacency.
- [ ] Gas & Convenience, Shopping, Recreation, Traffic as in v2.1.
- [ ] Calibration against known places, preview, owner approval, rollback switch.
- [ ] Re-dimension embeddings to the 13 v2.1+ factors (migration) at cutover.

## Wave 6 — Product and quality

- [ ] **Compare places.** Pin 2–4 places; side-by-side factor rings and differences.
- [~] **Data transparency page.** Sources, licences and freshness per source (from
  `ingestion_runs`).
- [~] **Feedback.** Thumbs up / down on AI summaries and chat answers; "this place is
  closed / wrong" reports feeding a review queue.
- [ ] **Chat v2.** Streaming replies (Lambda function URL), "ask about this area", saved
  conversations once sign-in exists, natural-language search ("quiet, near good coffee,
  20 min from JFK") as a first-class flow.
- [ ] **Browser tests.** Playwright E2E including WebKit (Safari) in CI; would have caught
  the Safari `removeChild` crash.
- [ ] **Monitoring.** CloudWatch alarms on 5xx and latency; LLM spend dashboard; ingestion
  failure alerts.
- [ ] **CI noise.** Stop the duplicate push-triggered run whose `ci-ok` always fails.
- [ ] **Before going public.** Rotate the Supabase password / service key, review the
  personal email in the geocoder User-Agent and the AWS account id in docs.

## Wave 7 — Phase 4: accounts, tiers and billing

- [ ] Google sign-in (Supabase Auth); `accounts`, `api_keys`, `usage_counters` with
  row-level security.
- [ ] Free / Pro / Business tiers with limits enforced in middleware (`429` + upgrade
  prompt).
- [ ] Stripe Checkout for Pro; Business via API keys, sales-assisted at first.
- [ ] Public API docs with keys and an OpenAPI playground.
- [ ] Saved places, saved anchors (work, gym), shareable reports and score-change alerts.

## Data backlog

- [ ] Quality ratings for gyms, restaurants, cafes, groceries (fills the v3 placeholders):
  Foursquare / Yelp / Google Places, each with licensing and caching limits.
- [ ] School-level ratings from state report cards (NYSED, NJ, CT EdSight).
- [ ] BTS National Transportation Noise Map (road, rail, aviation dB).
- [ ] NYC 311 noise complaints and DOB construction permits (NYC only).
- [ ] Safety (NYPD / state crime open data) — needs a careful fair-housing review first.
- [ ] Housing cost and affordability (Census ACS; free key).
- [ ] Parks quality, sidewalks, step-free stations (accessibility factors).
- [ ] Flood zones (FEMA) and air quality (EPA).
- [ ] Strava route popularity (API app needed).

## Future factors (for the weighted model)

Walkability, parks / green space (partly in Recreation), safety, commute to work,
downtown / main-street access, neighbourhood character, housing quality and
affordability, property taxes, highway access, healthcare access, social / nightlife
access, seasonal considerations. Each joins the normalized average with its own weight.

## Expansion (only with a traction signal)

- [ ] More metros (a whole-US build is roughly 30–50× today's data; revisit the database
  tier, PMTiles hosting and the precompute cost first).
- [ ] Commute-aware scoring per user (saved work address).
- [ ] Rent / price overlay and "similar but cheaper".
- [ ] Score history and change alerts.
