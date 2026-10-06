# BenriSpace — Planned Work

Everything planned but not shipped, in one place. [ROADMAP.md](ROADMAP.md) records goals,
what is done and the decisions log; this file is the backlog to pull from. Each item says
**why**, **how** and **what it depends on**. Status markers: `[ ]` planned,
`[~]` built or partly done (not fully in production), `[x]` done (move done items
to ROADMAP.md).

Last updated 2026-10-05.

---

## Wave 1 — Quick performance wins

- [x] **Spatial index on cells.** `geo_entities (latitude, longitude)` btree (migration 0011).
- [x] **Trigram search on places.** `pg_trgm` GIN index on `places.name` / `brand`.
- [x] **Covering index.** `scores (weights_version, geo_entity_id)`; the materialized view
  was skipped (measured no win).
- [x] **Lambda timeout 20 s → 29 s** so multi-tool chat answers fit.
- [x] **Connection reuse.** `/v1/score` p50 314 → 115 ms.
- [x] **Similar areas by SQL distance.** L2 over per-metro z-scored factor scores; pgvector
  embeddings and `similar_cells` dropped (migration 0016). Live 2026-10-05.
- [x] **Single-trip area scoring + 5-minute cache.** Live with the category nearest-place
  index (migration 0015): cold `/v1/area?precision=point` 230-440 ms from a laptop.
- [~] **Edge caching.** `infra/edge_cache.tf` (Cloudflare cache rules, off behind
  `enable_edge_cache`; needs SSL mode Full (strict) first). Not applied.
- [~] **Cold starts.** Measured: `import api.lambda_handler` ≈ 290 ms, nothing left to defer.
  The built score file is persisted (migration 0019), so a fresh instance reads one
  ~300 KB row instead of building for ~8 s. SnapStart not evaluated.
- [~] **Chat grounding tuned**, brand lookups (`find_places`, `near_brands`).

## Wave 2 — Instant filters and static delivery (Cloudflare R2)

- [x] **Compact score file** recoloured in the browser.
- [x] **Best areas computed locally.** Ranks whole areas from the per-area file (cells
  when it is missing); filter changes make no API call.
- [x] **Vector tiles.** `scripts/build_tiles.py` (tippecanoe in Docker) → PMTiles with
  `parents`, `cells`, `areas` layers, served from R2 via the manifest.
- [x] **R2 static delivery.** Bucket `benrispace-static` live at `tiles.benrispace.com`
  (CORS with Range). `scripts/publish_static.py` uploads content-hashed immutable files and
  rewrites the short-cache `manifest.json` last; the scoring workflow publishes the score
  file after each run. Production web reads the manifest (`NEXT_PUBLIC_STATIC_URL`, set in
  Terraform) and falls back to the API piece by piece. Live 2026-10-05.
- [x] **Precomputed per-area scores** (`api/areafile.py`, 28 bytes per area, 490 KB
  gzipped; 45-minute resumable build, `scripts/build_area_scores.py`). Polygon clicks show
  scores instantly; similar areas computed in the browser. Area scores and tiles are
  still published manually.
- [x] **Simplified polygon outlines in Postgres** (`scripts/copy_areas_slim.py`, ~3 m
  tolerance: -27 % vertices, 100 % lookup agreement; full detail only in the tiles). In
  prod since 2026-10-05 (35,943 areas, 27 MB); old `areas` / `area_cells` dropped.
- [ ] Trim the 11,369 `areas_slim` rows that lie outside the scored grid.
- [ ] Raw `feature_store` values archived to R2 as Parquet.

## Wave 3 — Data foundation

- [x] **Population density per cell** (Census 2020, migration 0012).
- [x] **PostGIS** geometry and GiST indexes; `road_segments` table and ingestion.
- [~] **Imperial column rename.** Expand (0020, applied in prod) / contract (0021, run
  only after a weekly ingestion succeeds on the new code) with `common/feature_columns.py`
  translating at the database boundary. `areas.area_sq_m` not renamed yet.
- [~] **Faster ingestion.** cKDTree for POIs, shops, transit, and now parks and schools
  (schools' nearest distance is now the true nearest).
- [x] **Density-capped road polygons.** 0.1 sq mi at ≥20k people/sq mi up to 1 sq mi below
  2k, split along tertiary then residential roads (35,943 areas). Live via
  `AREAS_TABLE=areas_slim` since 2026-10-05. 75 % of rural pieces are still straight tile
  cuts where OSM roads do not close loops.
- [x] **Storage compaction.** Smallint sub-scores, dropped id / embedding / unused
  columns (0016-0018), old area tables dropped. Production database 507 → 286 MB.
- [ ] **Density-tiered grid** (geohash6 where county density ≥ 200/sq mi, geohash5
  elsewhere) for a ~5 hour radius (~350 MB modelled; ARCHITECTURE.md section 10).

## Wave 4 — Routing precompute

- [~] **Walk / drive minutes per cell** (`ingestion/routing/`, Pandana, migration 0022).
  Full region computed locally from the Geofabrik networks in 25 min
  (`run --all --networks build/routing --steps amenity,graph,hubs`); 51 MB of tables.
  Moves to production with `scripts/copy_routing.py` (one transaction, size-guarded).
- [~] **Drive matrices** to airports and rail stations: computed for every cell on the
  arterial network (`pbf.py` `arterial` mode); ships with the copy above.
- [~] **Train times.** Connection Scan over GTFS rail, 933 stations, 273k connections,
  matrix in 24 s; refreshed locally, ships with the copy above.
- [~] **Isochrones** `GET /v1/isochrone` from a stored cell graph (pure Python, 2-27 ms);
  web "How far can I get?" card. Cell resolution is coarse: checked against routed
  area-to-area times, walking is within about +-30 % and driving within 0.85-1.05x in rural
  areas, 0.6-0.7x for 20-minute trips in dense suburbs (drive cells snap to collector roads,
  `travel.FastSnapper`). A finer or longer-range graph would tighten it.
- [~] **Real `/triangulate`** (cell-set intersect / union) and **optimizer upgrades**
  (Weiszfeld seed, lower-bound pruning, stored times).
- [x] **Geofabrik extract** instead of Overpass (`ingestion/routing/pbf.py`: NY/NJ/CT walk
  13.4M and drive 7.3M nodes in 2.5 min).
- [ ] **geohash5 coarse graph** for drive isochrones over ~90 minutes.
- [ ] **Triangulate / optimizer UI** in the web app.

## Wave 5 — Scoring v3 (`v3-timeaccess`) and cutover

- [~] **v2.2 routed density scoring** (`v2.2-density`, [SCORING.md](SCORING.md) A10). Places
  per sq mi over each area and its walkable neighbours on one absolute scale; drive-mode
  areas credit a dense cluster a short drive away (max 80 %); grocery / gym / gas 70 %
  proximity; transit = train station proximity. Built and calibrated locally (Lloyd, NY bars
  100 -> 30). Cutover: migration 0023, ingestion run, reach from production places,
  `scoring.area_run --write`, publish, switch `scoring_weights_version` + the repository
  variable. Not recomputed weekly yet (offline job).
- [ ] Run the reach + area scoring in CI (needs ~10 GB RAM for the walk network, or tiles).
- [ ] Better places coverage (Overture Maps): OpenStreetMap misses many gyms and shops.

- [ ] Per-factor time curves by travel mode, reading `cell_travel` ([SCORING.md](SCORING.md)
  Part B, A9).
- [ ] Dining density inside the neighbourhood polygon + a 10-minute walk.
- [ ] Transit service quality from GTFS frequencies.
- [ ] Noise by frontage band from `road_segments`; gas / convenience adjacency.
- [ ] Calibration against known places, preview, owner approval, rollback switch.

## Wave 6 — Product and quality

- [x] **Data transparency page**, **feedback**, **Playwright E2E** (Chromium + WebKit),
  **CI noise** (push trigger limited to main).
- [~] **Compare places**: pins, rings, points behind the best, biggest differences.
- [~] **Chat v2.** Inline "Ask Benri"; SSE status stream (`/v1/chat/stream`,
  `infra/chat_stream.tf` not applied). Reply arrives whole after grounding by design.
  Still to do: "ask about this area", natural-language search as a first-class flow.
- [~] **Monitoring.** `infra/alarms.tf` (SNS email + 4 CloudWatch alarms) applied; the
  email subscription needs confirming.
- [ ] **Before going public.** Rotate the Supabase password / service key, review the
  personal email in the geocoder User-Agent and the AWS account id in docs.

## Wave 7 — Phase 4: accounts, tiers and billing (not started)

- [ ] Google sign-in (Supabase Auth); `accounts`, `api_keys`, `usage_counters` with RLS.
- [ ] Free / Pro / Business tiers enforced in middleware (`429` + upgrade prompt).
- [ ] Stripe Checkout for Pro; Business via API keys.
- [ ] Public API docs with keys and an OpenAPI playground.
- [ ] Saved places, saved anchors, shareable reports, score-change alerts.

## Data backlog

- [ ] Quality ratings for gyms, restaurants, cafes, groceries (fills the v3 placeholders).
- [ ] School-level ratings from state report cards (NYSED, NJ, CT EdSight).
- [ ] BTS National Transportation Noise Map.
- [ ] NYC 311 noise complaints and DOB construction permits.
- [ ] Safety open data — needs a careful fair-housing review first.
- [ ] Housing cost and affordability (Census ACS).
- [ ] Parks quality, sidewalks, step-free stations.
- [ ] Flood zones (FEMA) and air quality (EPA).
- [ ] Strava route popularity.

## Future factors (for the weighted model)

Walkability, parks / green space (partly in Recreation), safety, commute to work,
downtown / main-street access, neighbourhood character, housing quality and
affordability, property taxes, highway access, healthcare access, social / nightlife
access, seasonal considerations.

## Expansion

- [ ] **~5 hour radius** (density-tiered grid, R2 offload; fits the free tier as modelled).
- [ ] **US and territories** (estimated 2-4 GB of Postgres, 1.5-2 GB with R2 offload;
  needs Supabase Pro and national data sources in place of state ones).
- [ ] **World** — separate project: storage is ~20-30 GB, but data sources (density,
  schools, transit, airports) are mostly US-only today.
- [ ] Commute-aware scoring per user; rent overlay; score history and alerts.
