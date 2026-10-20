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
  ingestion job. The next coverage target is a ~5 hour radius (about 10x today's
  land, 2.4x its population) on a density-tiered grid; the US with territories is
  estimated at 2-4 GB of Postgres (1.5-2 GB with polygons and raw features on R2),
  which needs a paid database tier. See ARCHITECTURE.md section 10.
- **Secondary goal.** The project doubles as a portfolio piece for a data
  engineering job search. The RAG pipeline, vector search and end-to-end ingestion
  pipeline are the target technical story, so favor architectural choices that
  are defensible and explainable over ones that are merely convenient.
- **Business model.** Leaning API-first licensing, not a consumer app as the
  primary revenue path: sell the convenience and optimizer scores to real estate
  platforms, relocation companies, brokerages and multifamily marketers (closest
  comp: Walk Score's licensing). The consumer app is the front door and demo.
  Reverse-search and location-intelligence ideas (amenity gaps, growth areas, factor
  quality, score history) are in PLANNED.md Wave 8.

## Status at a glance (2026-10-11)

| Area | State |
| --- | --- |
| Production | benrispace.com (Next.js on Amplify) and api.benrispace.com (FastAPI on Lambda) over Supabase Postgres (292 MB of 500 MB) and Cloudflare R2 static files |
| Scoring served | `v2.2-density` since 2026-10-06: 13 factors scored per road-bounded area from routed travel times, one absolute scale; `v2.1-handtuned` rows kept as the rollback |
| Areas | 35,943 density-capped road-hierarchy areas (0.1-1 sq mi) in `areas_slim`, simplified outlines; full detail in the PMTiles on R2 |
| Routing | Whole region precomputed from Geofabrik extracts: `cell_travel`, `cell_graph`, `cell_hubs`, `rail_matrix` |
| Migrations | 0002-0023 all applied |
| Features live | score, area click, address search, Best areas, improve, similar areas, places, compare, rule-based explanations (API only), optimizer, travel-time overlap with points of interest (auto-tuned mode and minutes), Ask Benri chat with map plans, MCP connector, data page, feedback, mobile sheet, Home, Login and Pricing (UI only) |
| Not applied | chat streaming infra, Cloudflare edge cache |
| Planned | automate the monthly v2.2 refresh, scoring v3, density-tiered grid for a 5 hr radius, auth and tiers |

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
- Scoring engine v1, v2 (cutover 2026-10-03), v2.1 (cutover 2026-10-04) and v2.2 density (cutover 2026-10-06).
- Click-to-polygon areas with neighborhood names: density-capped road-hierarchy areas
  (35,943, 0.1-1 sq mi) in `areas_slim`.
- Routing precompute for the whole region (Pandana over Geofabrik extracts, GTFS Connection
  Scan for trains) and cell-graph isochrones.
- API: score, area, suggest, reverse, places, improve, similar, map cells and top,
  isochrone, triangulate (routed travel-time overlap), optimize, explanations, chat, MCP,
  feedback, sources.
- Web app: Home, App (split-screen map and panel, mobile bottom sheet), API docs,
  Settings, Pricing and Login pages (UI only; auth and payments wiring still to do), light and dark themes with a
  recolored dark map, factor icons and pills, presets, importance sliders,
  readable addresses, shareable URLs, hover tooltips on ranked markers, travel mode and
  minutes in the search box, auto-tuned travel for overlapping areas, map centring on pins,
  and Ask Benri setting up the searched place and points of interest.

**Phase 3 pieces already shipped.**

- AI-written, grounded score explanations (Haiku 4.5, prompt `expl-v2`, cache and
  a $5/month cap). Removed 2026-10-15 to save credits, along with the app's Summary card;
  the explanation endpoints stay in the API with rule-based text.
- `/v1/improve` and the Improve card with named places (migration 0004).
- `/v1/similar` (first with pgvector embeddings, migration 0007; now SQL distance over per-metro
  z-scores, and computed in the browser from the area file).
- `/v1/optimize`, the multi-destination planner (work + Trader Joe's + Planet
  Fitness), with stored routed times and openrouteservice refinement.
- Ask Benri chat (tool-using Haiku with grounding validation) that can set up the searched place,
  points of interest and their overlap on the map, and the MCP connector for Claude.

**Phase 4 contract piece.** The OpenAPI auth schemes (`bearerAuth`, `apiKeyAuth`),
`401` and `429` responses and `X-RateLimit-*` headers were added to the contract
(non-breaking); nothing enforces them yet.

## In progress

- Nothing half-built on `dev-benrispace`; everything above is merged and deployed (PR #37,
  2026-10-11).

## Next

1. **Keep v2.2 fresh.** v2.2 (SCORING.md A10, live since 2026-10-06) and the routed travel
   tables are recomputed offline, not by the weekly job: run `reach --sync-places`,
   `scoring.area_run --write` and `publish_static.py --weights-version v2.2-density` about
   monthly (a CI workflow for it is the next piece of work). Delete the v2.1 rows after a week.
2. **Longer drive trips.** Add a geohash5 graph for drive trips over 90 min (the full routing
   run from Geofabrik extracts is done).
3. **Scoring v3 (`v3-timeaccess`).** Per-factor time curves reading `cell_travel`,
   frontage-based noise, quality placeholders. See [SCORING.md](SCORING.md) Part B.
4. **Density-tiered grid** (geohash6 where dense, geohash5 elsewhere) as the
   foundation for a ~5 hour radius.
5. **Natural-language search** as a first-class flow on top of the chat tools.

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

The wave-by-wave backlog (with status markers) lives in [PLANNED.md](PLANNED.md).

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
| 2026-10-04 | Nationwide expansion is not planned (superseded 2026-10-05) |
| 2026-10-04 | v2.1 cutover approved; robust normalization (clip at p2/p98 per metro) |
| 2026-10-05 | v1 and v2 score rows deleted (owner-run), database 447 MB to 328 MB |
| 2026-10-05 | On-demand point scoring (live PostGIS nearest-place lookups anchored to stored cell features) |
| 2026-10-05 | Area polygons sized by population density: 0.1 sq mi at 20k+/sq mi up to 1 sq mi below 2k, split along tertiary then residential roads, never across a hard road |
| 2026-10-05 | Similar areas: SQL distance over per-metro z-scored factor scores; pgvector embeddings and `similar_cells` dropped |
| 2026-10-05 | Routing: Pandana precompute per tile plus a stored cell graph for isochrones (pure Python in Lambda); Valhalla no longer needed. Train times from GTFS with the Connection Scan Algorithm |
| 2026-10-05 | Coverage target: ~5 hour radius on a density-tiered grid; static files move to Cloudflare R2 |
| 2026-10-06 | v2.2 cutover: production serves `v2.2-density` (per-area routed density, one absolute scale); v2.2 and routed tables refreshed monthly by hand |
| 2026-10-06 | `road_segments` no longer loaded weekly (97 MB, unread) |
| 2026-10-14 | Every travel mode starts at 10 minutes (the point of the site); steppers cap at walk 30, train 45, drive 60. Overlap tuning keeps the searched place at its own travel and gives only the far points of interest more time, switching mode past a mode's maximum. "Show on map" for the searched place's boundary moves into its search-box panel (default on); the Factors "Travel time" row is gone. Results are moved onto land |
| 2026-10-18 | Target data platform: Dagster (OSS) orchestration, dbt-duckdb transforms over Parquet on a private R2 bucket, pipeline compute on an ephemeral EC2 spot runner, dbt tests + asset checks + a release gate before publish ([DATA_PLATFORM.md](DATA_PLATFORM.md)); supersedes "GitHub Actions for orchestration" once cut over |
| 2026-10-10 | Travel mode and minutes live in the search box; overlap travel is auto-tuned once per set of places; chat can set up the map; Login and Pricing ship as UI only (Pro $9/mo or $90/yr placeholder) |

Other standing decisions: precompute scores rather than
compute live; GitHub Actions for orchestration (Airflow deferred); Business tier
sales-assisted first; rate limiting via a Postgres counter first.

## Build sequencing guidance

- Schema and API contract: single owner, direct work, first.
- Ingestion scripts: mechanical and independent once the schema is locked, so
  good candidates for parallel work.
- Routing precompute: independent batch job, can run alongside ingestion.
- Scoring engine design: direct work, not delegated; this is where the product's
  judgment and defensibility live.
- API integration and the RAG layer: after scoring and routing exist.
- Auth and billing: after the product works end to end; the sign-in UI can be
  scaffolded early against a mocked account.

## Open items and housekeeping

- Delete the `v2.1-handtuned` rollback rows (about 25 MB) once v2.2 has run cleanly.
- Wire the Login and Pricing pages to real auth and payments (Phase 4).
- Not yet verified: Safari and Firefox, screen readers, real touch devices.
- NCES public-domain status should be verified before launch
  ([data-sources.md](data-sources.md)).
- **Before making the repo public:** rotate the Supabase database password and
  service-role key (both were pasted in chat earlier); decide whether to keep the
  personal email and AWS account ID that appear in docs, `api/geocoding.py` and
  `common/overpass.py`; enable GitHub secret scanning. README and LICENSE (MIT)
  already exist.
