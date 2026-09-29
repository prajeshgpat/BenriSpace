# BenriSpace — Project Instructions & Architecture

## Overview

BenriSpace (formerly CNVNT) is a location-convenience platform that scores
addresses based on walkability (urban) or drivability (suburban) to daily-life
amenities, and lets users triangulate ideal areas based on multiple anchor
points (job, school, family, landmarks) rather than a single static score.

**Core product shift:** not "here's a convenience score for this address" but
"given where you need to be, where should you actually live?" — a multi-anchor
triangulation solver, not a lookup tool.

**Origin insight:** retailers like Starbucks/Whole Foods/Target cluster in
more desirable neighborhoods than Walmart/Popeyes — proximity to certain
amenity _types_ is a usable proxy for neighborhood quality.

**v1 scope:** NYC metro, 1–2 hour radius — five boroughs, Long Island,
Westchester, Hudson Valley, northern NJ, Fairfield County CT. This radius
spans multiple transit agencies (MTA, LIRR, Metro-North, NJ Transit) and
multiple counties' school data sources — treat each as a separate ingestion
job, not one unified feed.

**Secondary goal:** this project doubles as a portfolio piece for a data
engineering job search. The RAG pipeline + vector search + end-to-end
ingestion pipeline is the target technical story. Favor architectural choices
that are defensible and explainable in an interview over ones that are merely
convenient.

---

## Scoring Factors

| Factor                                                              | Signal direction                                                                 | Data source                                                            |
| ------------------------------------------------------------------- | -------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| Grocery stores, gyms, cafes                                         | Positive                                                                         | OSM Overpass                                                           |
| Gas stations / convenience store density                            | Negative (proxy for less desirable clientele)                                    | OSM Overpass                                                           |
| Train/transit accessibility                                         | Positive                                                                         | GTFS static feeds (per agency)                                         |
| School quality                                                      | Positive                                                                         | NYC Open Data + surrounding county sources                             |
| Road/traffic conditions (e.g. single-lane roads causing congestion) | Negative                                                                         | OSM road classification tags                                           |
| Emergency vehicle route noise                                       | Negative (mitigated by street orientation — side street vs. facing the corridor) | OSM road classification (proxy only — phase 2 refinement, not precise) |
| Proximity to tier-1 airports (JFK, Dulles, SFO-class)               | Positive                                                                         | Hardcoded list + drive time via routing engine                         |

Scores are a **weighted composite of normalized sub-scores**, hand-tuned
initially (no training data to fit against yet). Document weight rationale —
it's the defensibility story for both users and future ML refinement.

---

## Architecture — Build in Phases

### Phase 0 — Contracts (do first, do not parallelize)

Define before any other work starts:

- Feature-store schema (one row per address/geohash, raw counts/distances per
  category)
- API request/response contract (score endpoint, explanation endpoint,
  isochrone/triangulation endpoint)

Everything downstream depends on these. Getting this wrong means redoing
parallel work later.

### Phase 1 — MVP, single metro

- **POIs**: OSM Overpass API (free, no key) — grocery, gyms, cafes, gas
  stations/convenience stores
- **Transit**: GTFS static feeds, one ingestion job per agency (MTA, LIRR,
  Metro-North, NJ Transit)
- **Schools**: NYC Open Data + surrounding county open-data sources
- **Roads**: OSM road classification tags (`highway=primary/secondary/...`)
  for congestion and emergency-corridor proxies
- **Airports**: hardcoded lat/longs (JFK, Dulles, SFO-class), drive time via
  self-hosted routing engine
- **Ingestion orchestration**: GitHub Actions scheduled workflow — sufficient
  for weekly/monthly refresh cadence. Do not reach for Airflow yet; it's
  unnecessary operational overhead at this scale.
- **Storage**: Supabase free tier (Postgres + pgvector included — same
  instance serves the embeddings work in Phase 3, no separate vector DB
  needed)
- **Scoring**: precomputed and stored, never calculated live per request.
  This is the key scalability lever — it keeps live user traffic from ever
  touching rate-limited third-party APIs.
- **API**: FastAPI, deployed on Cloud Run or Render free tier (scales to
  zero when idle)
- **Frontend**: existing Firebase Hosting setup, pointed at the new API

### Phase 2 — Triangulation / Isochrones

- Use **Valhalla** (self-hosted, Docker) for isochrone generation — not
  OSRM. OSRM does routing but isn't built for isochrones; Valhalla has native
  isochrone support and is the standard tool for this.
- **Invert the expensive direction**: compute isochrones from the small
  number of user-provided anchor points (job, school, landmark — typically
  2-4 per session), not per candidate address. Precomputing isochrones for
  every address in the metro doesn't scale on a free-tier budget; computing
  them per user session does.
- Intersect/union the anchor isochrones, then rank the already-precomputed
  address scores that fall inside the resulting area.

### Phase 3 — AI / RAG Layer

- **Architecture: RAG, not fine-tuning.** Underlying data changes
  constantly (new POIs, transit changes, recalculated scores); RAG retrieves
  current data at query time, a fine-tuned model would go stale immediately.
  RAG also constrains the LLM to only discuss what's actually in retrieved
  data — critical here, since a hallucinated "great coffee shop nearby" is a
  trust-breaking failure mode for this specific product.
- **Natural-language query parsing**: user intent ("somewhere quiet, near
  good coffee, 20 min from JFK") → structured filter query → retrieval
  against the feature table. This is the primary RAG pipeline and the
  strongest portfolio artifact in the project.
- **Score explanation generation**: retrieve an address's stored factor
  breakdown, generate the human-readable "why this scored 8.4" explanation.
- **"Similar neighborhoods" search**: embeddings over neighborhood feature
  vectors via pgvector, semantic nearest-neighbor search.
- Model choice matters less than retrieval/data quality — any competent
  instruction-following model works fine as the generation layer.

### Phase 4 — Feature Expansion (post-MVP, only with traction signal)

- Commute-aware scoring (actual workplace → commute time via GTFS + routing
  engine, not generic "near transit")
- Budget/rent overlay (cross-reference score with rent/price data)
- Side-by-side neighborhood comparison (2-3 addresses on the same factor
  breakdown)
- Multi-metro expansion — only at this point consider Airflow (multiple
  refresh cadences across metros justifies an orchestrator) and paid Places
  API for coverage gaps OSM can't fill

---

## Build Sequencing Guidance

- **Schema + API contract**: single owner, direct work, do first — the
  foundation everything else depends on.
- **Data ingestion scripts** (OSM POIs, GTFS per agency, schools, roads):
  good candidates for parallel/subagent work once the schema is locked —
  mechanical, independent, well-specified tasks.
- **Valhalla isochrone service setup**: independent infra task, can run in
  parallel with ingestion work.
- **Frontend scaffolding**: can start early against a mocked API response,
  doesn't need to wait on real data.
- **Scoring engine design**: keep as direct work, not delegated to a
  subagent — this is where the product's judgment and defensibility live.
- **API integration + RAG layer**: sequential, after scoring + isochrone
  services exist.

---

## Business Model

Leaning **API-first/licensing**, not a consumer-facing app as the primary
revenue path: sell the convenience/triangulation score to real estate
platforms, relocation companies, brokerages, and multifamily marketers.
Closest comp is Walk Score's licensing model (historically embedded on
Redfin/Zillow listings). The consumer-facing app is more valuable right now
as a demo/portfolio piece than as a standalone product — build it as the
front door that gets B2B conversations started, not as the end goal.

---

## Cost Constraints

Phase 1 should run close to **$0/month**: Supabase free tier, Cloud
Run/Render free tier, GitHub Actions free minutes, OSM/GTFS/NYC Open Data all
free, self-hosted Valhalla/OSRM in a Docker container. The only realistic
early cost is LLM API calls in Phase 3 — keep these capped and per-request
cheap; don't add paid data sources (e.g. Google Places) until free sources
prove insufficient with real usage data to justify the spend.
