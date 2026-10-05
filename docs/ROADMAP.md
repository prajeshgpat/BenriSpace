# BenriSpace — Roadmap

Product goals, build phases, current status and the decisions log. For how the
system works see [ARCHITECTURE.md](ARCHITECTURE.md); for the scoring model see
[SCORING.md](SCORING.md).

## Goals

BenriSpace (formerly CNVNT) is a location-convenience platform. It scores
addresses on how convenient daily life is there (walking in dense areas,
driving in suburbs) and lets people find the right area given where they need to
be. The core product shift is not "here is a convenience score for this address"
but "given where you need to be, where should you actually live?": a
multi-destination solver, not a lookup tool.

- **Origin insight.** Retailers like Starbucks, Whole Foods and Target cluster in
  more desirable neighborhoods than Walmart or Popeyes, so proximity to certain
  amenity types is a usable proxy for neighborhood quality.
- **Scope.** The New York metro only, within about two hours of the city: the five
  boroughs, Long Island, Westchester, the Hudson Valley, northern New Jersey and
  Fairfield County, CT. The radius spans several transit agencies, each a separate
  ingestion job. Nationwide expansion is **not planned** (the cell grid would be
  about 17-20 GB for the US; tract-level polygons about 150 MB).
- **Secondary goal.** The project doubles as a portfolio piece for a data
  engineering job search. The RAG pipeline, vector search and end-to-end ingestion
  pipeline are the target technical story, so favor architectural choices that
  are defensible and explainable over ones that are merely convenient.
- **Business model.** Leaning API-first licensing, not a consumer app as the
  primary revenue path: sell the convenience and optimizer scores to real estate
  platforms, relocation companies, brokerages and multifamily marketers (closest
  comp: Walk Score's licensing). The consumer app is the front door and demo.

## Status at a glance (2026-10-04)

| Area | State |
| --- | --- |
| Production | benrispace.com (Next.js on Amplify) and api.benrispace.com (FastAPI on Lambda) over Supabase Postgres |
| Scoring served | `v2-handtuned`, 14 factors, 64,320 rows (cutover 2026-10-03) |
| Scoring built | `v2.1-handtuned`, 13 pills; full ingestion in progress; cutover pending owner approval |
| Areas | 49,158 road-bounded areas capped at 0.8 sq mi, with neighborhood names (migration 0008 applied) |
| Features live | score, area click, address search, Best areas, improve-this-area, similar areas, places, AI explanations, multi-destination optimizer, map, mobile sheet, Home page |
| In progress | Ask BenriSpace chat (`/v1/chat`, migration 0010 not applied) |
| Planned | Valhalla routing precompute, imperial column rename, scoring v3, auth and tiers |

## Done

**Phase 0: contracts.** Feature-store schema (`contracts/schema.sql`), API contract
(`contracts/openapi.yaml`), normalization approach (now [SCORING.md](SCORING.md)).

**Phase 1: MVP for the NYC metro, live in production.**

- Domain, DNS and Terraform stages 1 and 2 (state bucket, Lambda, API Gateway,
  SSM, OIDC deploy role, budget alert, ACM, custom domains, Amplify, Cloudflare
  records), the Lambda packaging and deploy workflow, and the `execute-api`
  address closed.
- Grid (64,320 geohash6 cells), and ingestion for OSM POIs, GTFS transit (MTA,
  LIRR, Metro-North, PATH, NJ Transit's open feeds, plus OSM stops), schools
  (NCES + EDFacts), roads and noise-corridor facilities, airports, trails,
  shopping and parks (v2.1), and neighborhood names.
- Weekly orchestration in GitHub Actions (sequential jobs, scoring after).
- Scoring engine v1, v2 (cutover 2026-10-03) and v2.1 (built).
- Click-to-polygon areas, rebuilt at 0.8 sq mi (49,158 areas) with neighborhood
  names.
- API: score, area, suggest, reverse, places, improve, similar, map cells and top,
  triangulate (placeholder), optimize, explanations.
- Web app: Home, App (split-screen map and panel, mobile bottom sheet), API docs,
  Settings, Pricing and Login placeholders, light and dark themes with a
  recolored dark map, factor icons and pills, presets, importance sliders,
  readable addresses, shareable URLs, hover tooltips on ranked markers.

**Phase 3 pieces already shipped.**

- AI-written, grounded score explanations (Haiku 4.5, prompt `expl-v2`, cache and
  a $5/month cap).
- `/v1/improve` and the Improve card with named places (migration 0004).
- `/v1/similar` with pgvector embeddings (migration 0007; see the status note in
  ARCHITECTURE.md).
- `/v1/optimize`, the multi-destination planner (work + Trader Joe's + Planet
  Fitness), with openrouteservice refinement.

**Phase 4 contract piece.** The OpenAPI auth schemes (`bearerAuth`, `apiKeyAuth`),
`401` and `429` responses and `X-RateLimit-*` headers were added to the contract
(non-breaking); nothing enforces them yet.

## In progress

- **v2.1 full ingestion and cutover.** Ingestion for the new columns is running;
  the cutover (set `scoring_weights_version` to `v2.1-handtuned` and apply)
  waits for owner approval.
- **Ask BenriSpace chat.** `/v1/chat`, a tool-using Haiku assistant limited to
  read-only tools, with grounding validation, budget cap and a per-visitor daily
  cap. Migration 0010 (`chat_usage`) is not applied; the API skips the limit
  while the table is missing.

## Next

1. **Valhalla routing precompute.** Walk, drive and transit minutes per cell in a
   batch run (Docker on a laptop; Docker and Colima are installed locally; or a
   short-lived AWS spot instance). Replaces straight-line airport drive times and
   the estimates in the optimizer and scoring v3. Valhalla, not OSRM (native
   isochrones). Compute isochrones from the 2-4 anchor points, not per candidate.
   Live triangulation from arbitrary addresses uses a hosted routing free tier.
   Intersect or union the anchor isochrones, then rank the precomputed scores
   inside. This turns the `/triangulate` placeholder into the real thing.
2. **Imperial column rename.** Older raw `feature_store` columns are still metres
   (`*_m`); the newer ones are imperial. Rename for consistency.
3. **Scoring v3 (`v3-timeaccess`).** Absolute time-to-access curves per factor and
   travel mode, mode chosen by population density (2020 Census block groups),
   frontage-based noise, quality placeholders. Fixes the min-max outlier
   weakness. Needs the Valhalla minutes and the 2020 Census density data. See
   [SCORING.md](SCORING.md) Part B.
4. **Natural-language search.** User intent ("somewhere quiet, near good coffee,
   20 minutes from JFK") to a structured filter to retrieval against the feature
   table. The strongest portfolio artifact; builds on the chat tools.
5. **Compare locations**, a data transparency page, a feedback loop, and public API
   docs with keys and an OpenAPI playground (Business tier).
6. **Neighborhood polygons scored directly** (5-10 block clusters bounded by
   secondary roads, instead of averaging grid cells). Stage 1 (offline prototype
   in `ingestion/areas/`) exists; stage 2 (full-metro run) and stage 3
   (per-polygon scoring, API and UI) are not started.

## Later

- **Phase 4: auth, tiers and billing.** Google sign-in via Supabase Auth (same
  project; Google-only is enough, no email/password until needed). Additive tables
  only, no retrofit of the shared reference data: `accounts` (maps to
  `auth.users`, holds `tier` and `stripe_customer_id`), `api_keys` (hashed,
  account-scoped, Business tier) and `usage_counters`, with row-level security from
  day one. Tiers:

  | Tier | Access | Initial limits (tune with usage) | Billing |
  | --- | --- | --- | --- |
  | Free | Web UI only | 50 score lookups/day, 10 triangulations/day, no NL/RAG queries | none |
  | Pro | Web UI only | about 2,000 score lookups/day, 200 triangulations/day, 100 NL/RAG queries/day, saved anchors | self-serve, Stripe Checkout |
  | Business | API key, programmatic | custom volume plus usage-based overage | sales-assisted and manually invoiced at first |

  Rate limiting starts as a Postgres counter check in FastAPI middleware
  (`429` + `Retry-After` + upgrade prompt, not a silent drop); move to Redis or
  Upstash only when request volume itself makes the round-trip the bottleneck.
  Business stays sales-assisted until there is demand for self-serve. Free-tier
  limits exist to protect the cost budget, not just to segment pricing. Needs a
  domain email, a Google Cloud OAuth client (origin `https://benrispace.com`,
  redirect `https://<project>.supabase.co/auth/v1/callback`) and a Stripe account.
- **Phase 5: expansion, only with a traction signal.** Commute-aware scoring
  (actual workplace to commute time via GTFS and routing), budget and rent overlay,
  side-by-side comparison, multi-metro expansion (only then consider Airflow and a
  paid Places API for gaps OSM cannot fill).
- Saved places and shareable reports; safety, flood and air quality; personalised
  weights and presets; a cost layer; score history and alerts; accessibility
  factors; the future scoring factors listed in SCORING.md section 9.
- Real quality data (gyms, restaurants, groceries) and school-level ratings.
- Strava route popularity (needs an API app; see SCORING.md A5 for the cost
  trade-off).

## Improvement plan

Waves in rough order. All items are **planned** unless marked in flight.

- **Wave 0 (in flight):** chat v1; web polish and docs; full ingestion, then v2.1 preview, then cutover (owner approval).
- **Wave 1, quick performance wins (planned):**
  - `(latitude, longitude)` index on `geo_entities`.
  - Rewrite the similar-areas query to use the HNSW index (fetch the target vector, then `ORDER BY embedding <-> vec`).
  - `pg_trgm` GIN index for brand search on `places`.
  - Covering index on `scores(weights_version, geo_entity_id)`.
  - Materialized view `latest_scores`.
  - Precomputed top-20 similar cells per cell.
  - Cloudflare edge caching for GET endpoints.
  - Lambda cold-start cuts (lazy imports, consider SnapStart).
- **Wave 2, client-side scoring and tiles (planned):**
  - Static per-cell sub-score file (13 x uint8 per cell, about 300 KB gzipped) on Cloudflare R2, so filter and weight changes recolor the map and rank top areas in the browser with no API call (heap top-k plus grid-hash spacing).
  - PMTiles vector tiles (tippecanoe) for the cell grid and area polygons.
- **Wave 3, v3 data foundation (planned):**
  - Imperial column rename using expand/contract migrations.
  - Census 2020 population density per cell (car below 10,000 people per sq mi).
  - PostGIS geometry columns with GiST indexes (areas, places, cells, major-road lines), replacing bbox plus Python point-in-polygon.
  - Ingestion speedups (scipy cKDTree and numpy; parallel non-Overpass jobs).
- **Wave 4, routing precompute (planned):**
  - Pandana multi-source k-nearest network search per amenity category (walk and drive).
  - OSRM table (contraction hierarchies) for drive matrices to airports and stations.
  - r5py RAPTOR station-to-station transit matrix.
  - Optimizer seeded by the weighted geometric median (Weiszfeld), with lower-bound pruning and precomputed train times.
  - (Valhalla, decided 2026-10-04, remains the plan for isochrones and per-cell minutes; this wave's tools are candidates for the bulk matrices.)
- **Wave 5, scoring v3 and cutover (planned):** per-factor curves, density-based modes, dining density in polygon plus a 10-minute walk, transit service quality from GTFS frequencies, noise by frontage band from road geometry, gas and convenience adjacency; calibration against known places; preview and rollback.
- **Wave 6, product and quality (planned):**
  - Compare 2-4 places.
  - Data transparency page (sources and freshness from `ingestion_runs`).
  - Feedback (thumbs on AI text, report a closed place).
  - Chat streaming and ask-about-this-area.
  - Playwright E2E including WebKit (Safari) in CI.
  - CloudWatch alarms and an LLM spend dashboard.
  - Fix the duplicate push-run `ci-ok` failure.
  - Rotate secrets before making the repo public.
- **Wave 7, Phase 4 (planned):** Google sign-in, tiers, API keys and an OpenAPI playground, Stripe, saved places and shareable reports.
- **Later data:** BTS noise map, school-level ratings (state report cards), a quality ratings source, safety and affordability (Census ACS).

## Decisions log

| Date | Decision |
| --- | --- |
| 2026-09-28 | Domain registered at Cloudflare Registrar; DNS stays at Cloudflare, managed by Terraform as DNS-only records |
| 2026-09-28 | Trail popularity added as a factor (OSM trails required, Strava optional); Garmin dropped (no public aggregate API) |
| 2026-09-29 | Backend and frontend moved from GCP and Firebase to AWS (Lambda + API Gateway, Amplify): resume breadth, not cost |
| 2026-09-29 | Use the Supabase Session pooler connection string (direct host is IPv6-only) |
| 2026-10-02 | Secondary roads and above are hard barriers for neighborhood polygons |
| 2026-10-02 | School score is 20% proximity + 80% district rating, `NULL` when unrated; ratings from EDFacts via the Urban Institute portal (ODC-By); GreatSchools link-only (licensed); Stanford SEDA rejected (non-commercial terms) |
| 2026-10-03 | v2 cutover: production serves `v2-handtuned` |
| 2026-10-03 | LLM: Anthropic Haiku 4.5, about $5/month cap, RAG not fine-tuning; "similar" starts with cells; "improve" uses named places |
| 2026-10-03 | PATH GTFS and OSM transit stops added to cover NJ and CT gaps |
| 2026-10-04 | NJ Transit uses its open official rail and bus feeds; no API key needed (this retires the old blocker) |
| 2026-10-04 | Scoring framework v1.2-v1.4 (owner decisions): overall normalized to selected filters and out of 100; Gas & Convenience is one positive factor and still a noise source when adjacent; travel mode by density (car below 10,000 people per sq mi, walk plus transit at or above); quality components are placeholders; schools 20/80 confirmed; no reserved weight; restaurants, cafes and bars stay separate pills; weights follow frequency of use with diminishing returns; noise scored by position relative to the road; weights and mode-aware adjustment accepted; every factor is a pill (Recreation and Shopping replace the hidden signals); icons: airport plane, noise corridor siren, "Bars", "Traffic"; per-factor, per-mode proximity curves; neighborhood polygons capped at 0.8 sq mi |
| 2026-10-04 | Routing: precompute with Valhalla (batch run, then store minutes per cell) |
| 2026-10-04 | Nationwide expansion is not planned |

Other standing decisions: Valhalla over OSRM; precompute scores rather than
compute live; GitHub Actions for orchestration (Airflow deferred); Business tier
sales-assisted first; rate limiting via a Postgres counter first.

## Build sequencing guidance

- Schema and API contract: single owner, direct work, first.
- Ingestion scripts: mechanical and independent once the schema is locked, so
  good candidates for parallel work.
- Valhalla setup: independent infrastructure task, can run alongside ingestion.
- Scoring engine design: direct work, not delegated; this is where the product's
  judgment and defensibility live.
- API integration and the RAG layer: after scoring and routing exist.
- Auth and billing: after the product works end to end; the sign-in UI can be
  scaffolded early against a mocked account.

## Open items and housekeeping

- Confirm migration 0006 and 0007 status in production (file headers still say
  "not applied"), then update those headers.
- Apply migration 0010 when chat is ready to ship.
- Delete the retired v1 score rows (64,320 rows of `v1-handtuned`, kept only for
  rollback and now dead weight) with `scripts/delete_v1_scores.py`. It is
  owner-run: a dry run by default (row counts and database size), `--yes` deletes
  in batches of 5,000, and it prints counts and size before and after. It refuses
  to run if the API is configured to serve v1. File size only shrinks after
  `vacuum full scores;`.
- Apply migration 0013 (`score_scales`) to let `scoring/run.py` store the factor
  scales used by on-demand point scoring (`precision=point`); until then the API
  computes them once per Lambda instance from `feature_store` (0.2 to 2.5 s per metro).
- Not yet verified: Safari and Firefox, screen readers, real touch devices.
- NCES public-domain status should be verified before launch
  ([data-sources.md](data-sources.md)).
- **Before making the repo public:** rotate the Supabase database password and
  service-role key (both were pasted in chat earlier); decide whether to keep the
  personal email and AWS account ID that appear in docs, `api/geocoding.py` and
  `common/overpass.py`; enable GitHub secret scanning. README and LICENSE (MIT)
  already exist.
