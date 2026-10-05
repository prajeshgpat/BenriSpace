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

## Status at a glance (2026-10-05)

| Area | State |
| --- | --- |
| Production | benrispace.com (Next.js on Amplify) and api.benrispace.com (FastAPI on Lambda) over Supabase Postgres (328 MB of 500 MB after deleting v1 and v2 scores) |
| Scoring served | `v2.1-handtuned`, 13 factor pills, 64,320 rows; v1 and v2 rows deleted 2026-10-05 |
| Areas | Production: 49,158 road-bounded areas capped at 0.8 sq mi. `scratch`: density-capped road-hierarchy areas (0.1-1 sq mi, 35,943 areas) in local `areas_slim`, cutover pending |
| Features live | score, area click, address search, Best areas, improve, similar areas, places, AI explanations, optimizer, Ask Benri chat, data page, feedback, map, mobile sheet, Home page |
| On `scratch` (owner testing) | on-demand point scoring, inline Ask Benri with brand lookups, density-capped polygons, routing precompute + isochrones + real triangulate, storage compaction, browser-side best areas, PMTiles (flag), compare differences, chat streaming (infra not applied) |
| Planned | Full routing run, scoring v3, density-tiered grid for a 5 hr radius, auth and tiers |

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
- `/v1/similar` (first with pgvector embeddings, migration 0007; SQL distance on `scratch`; see
  ARCHITECTURE.md).
- `/v1/optimize`, the multi-destination planner (work + Trader Joe's + Planet
  Fitness), with openrouteservice refinement.

**Phase 4 contract piece.** The OpenAPI auth schemes (`bearerAuth`, `apiKeyAuth`),
`401` and `429` responses and `X-RateLimit-*` headers were added to the contract
(non-breaking); nothing enforces them yet.

## In progress

- **`scratch` branch, owner testing.** Everything listed above as "On `scratch`".
  Production rollout needs these migrations, in order, each owner-approved:
  0014 `areas_slim` (then the slim area build and `AREAS_TABLE=areas_slim`),
  0015 `places_cat_geom_gist`, 0020 imperial expand (deploy + one ingestion run
  before continuing), 0016 drop embeddings, 0017 compact scores, 0018 trim
  `geo_entities`, 0019 `score_files` (then `python -m api.scorefile`), 0022
  routing (then `python -m ingestion.routing.run --all`), and last 0021 imperial
  contract (irreversible). Details: ARCHITECTURE.md storage model and migrations table.

## Next

1. **Ship `scratch`** after owner testing (PR to dev-benrispace, then main).
2. **R2 static delivery (built on `scratch`, files live).** Score file, PMTiles and
   per-area scores are on `tiles.benrispace.com` behind a versioned manifest; the web
   reads them when `NEXT_PUBLIC_STATIC_URL` is set. Remaining: set the env var in
   Amplify, copy simplified polygons to prod. See PLANNED.md Wave 2.
3. **Full routing run.** Swap Overpass for a Geofabrik extract, run walk and drive
   tiles for the whole metro, and add a geohash5 graph for drive trips over 90 min.
4. **Scoring v3 (`v3-timeaccess`).** Per-factor time curves reading `cell_travel`,
   frontage-based noise, quality placeholders. See [SCORING.md](SCORING.md) Part B.
5. **Density-tiered grid** (geohash6 where dense, geohash5 elsewhere) as the
   foundation for a ~5 hour radius.
6. **Natural-language search** as a first-class flow on top of the chat tools.

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

- Migrations 0014-0022 are written but not applied (order under "In progress").
- Not yet verified: Safari and Firefox, screen readers, real touch devices.
- NCES public-domain status should be verified before launch
  ([data-sources.md](data-sources.md)).
- **Before making the repo public:** rotate the Supabase database password and
  service-role key (both were pasted in chat earlier); decide whether to keep the
  personal email and AWS account ID that appear in docs, `api/geocoding.py` and
  `common/overpass.py`; enable GitHub secret scanning. README and LICENSE (MIT)
  already exist.
