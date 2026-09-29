# BenriSpace — Phase Breakdown

Detailed breakdown of each build phase from `PROJECT.md`. This file expands
each phase into concrete tasks, deliverables, and exit criteria. See
`PROJECT.md` for overall architecture, scoring factors, and business context.

---

## Phase 0 — Contracts

**Goal:** Lock the interfaces everything else depends on, before any
parallel work starts.

**Do not parallelize this phase.** Getting these wrong means redoing
downstream work.

### Tasks

- [x] Design feature-store schema — one row per address/geohash, raw
      counts/distances per POI category (grocery, gyms, cafes, gas stations,
      transit stops, schools, road classification, airport drive time)
- [x] Define API request/response contract:
  - [x] Score endpoint (address/geohash in → composite score + sub-scores
        out)
  - [x] Explanation endpoint (address in → human-readable factor breakdown
        out)
  - [x] Isochrone/triangulation endpoint (anchor points in → ranked
        addresses out)
- [x] Document normalization approach for raw sub-scores (so weighting in
      Phase 1 has a consistent input range)

### Deliverables

- Feature-store schema (SQL DDL or equivalent) — `contracts/schema.sql`
- API contract spec (OpenAPI/JSON schema) — `contracts/openapi.yaml`
- Normalization approach — `contracts/normalization.md`

### Exit criteria

Schema and API contract are reviewed and stable enough that ingestion,
scoring, and frontend work can proceed independently without expecting
breaking changes.

---

## Phase 1 — MVP, Single Metro

**Goal:** End-to-end pipeline for one metro (NYC, 1–2 hr radius) with
precomputed scores served through an API.

**Dependencies:** Phase 0 schema/contract locked.

### Tasks

- [ ] **POI ingestion (OSM Overpass)** — grocery, gyms, cafes, gas
      stations/convenience stores
- [ ] **Transit ingestion (GTFS static)** — one ingestion job per agency:
  - [ ] MTA
  - [ ] LIRR
  - [ ] Metro-North
  - [ ] NJ Transit
- [ ] **School data ingestion** — NYC Open Data + surrounding county
      open-data sources (treat each county as a separate source, not a
      unified feed)
- [ ] **Road classification ingestion** — OSM `highway=*` tags, for
      congestion and emergency-corridor proxies
- [ ] **Airport proximity** — hardcoded lat/longs (JFK, Dulles, SFO-class) +
      drive time via self-hosted routing engine
- [ ] **Ingestion orchestration** — GitHub Actions scheduled workflow
      (weekly/monthly cadence; no Airflow yet)
- [ ] **Storage** — Supabase free tier (Postgres + pgvector)
- [ ] **Scoring engine** — weighted composite of normalized sub-scores,
      hand-tuned weights, precomputed and stored (never live per-request)
- [ ] **API** — FastAPI, deployed to Cloud Run or Render free tier
- [ ] **Frontend** — point existing Firebase Hosting setup at the new API

### Deliverables

- Populated feature store for the full v1 metro radius
- Precomputed composite + sub-scores for all addresses/geohashes in scope
- Live API serving score + explanation data
- Frontend displaying scores for a searched address

### Exit criteria

A user can search an address in the NYC metro radius and get back a
composite score with sub-factor breakdown, sourced entirely from
precomputed data (no live third-party API calls on the request path).

---

## Phase 2 — Triangulation / Isochrones

**Goal:** Let users rank addresses by proximity to multiple anchor points
(job, school, landmark) instead of a single static score.

**Dependencies:** Phase 1 precomputed scores exist.

### Tasks

- [ ] Stand up **Valhalla** (self-hosted, Docker) for isochrone generation
      — not OSRM (routing-only, no native isochrone support)
- [ ] Build anchor-point input flow (2–4 anchors per user session: job,
      school, landmark, etc.)
- [ ] Compute isochrones **from anchor points**, not per candidate address
      — inverts the expensive direction so it scales on a free-tier budget
- [ ] Intersect/union anchor isochrones into a single candidate area
- [ ] Rank precomputed address scores that fall inside the resulting area
- [ ] Wire triangulation endpoint (from Phase 0 contract) to this pipeline

### Deliverables

- Valhalla service running in Docker, reachable by the API
- Triangulation endpoint returning ranked addresses for a set of anchors

### Exit criteria

A user can input 2–4 anchor points and get back a ranked list of addresses
that fall within the intersected/unioned isochrone area, ordered by
precomputed score.

---

## Phase 3 — AI / RAG Layer

**Goal:** Natural-language interface over the scoring data, using
retrieval-augmented generation — not fine-tuning, since underlying data
changes constantly and a fine-tuned model would go stale immediately. RAG
also constrains the LLM to only discuss retrieved data, which matters here
because a hallucinated amenity claim is a trust-breaking failure mode.

**Dependencies:** Phase 1 feature store + scores; pgvector already
provisioned via Supabase (Phase 1).

### Tasks

- [ ] **Natural-language query parsing** — user intent ("somewhere quiet,
      near good coffee, 20 min from JFK") → structured filter query →
      retrieval against the feature table (primary RAG pipeline; strongest
      portfolio artifact in the project)
- [ ] **Score explanation generation** — retrieve an address's stored
      factor breakdown, generate the "why this scored 8.4" explanation
- [ ] **"Similar neighborhoods" search** — embeddings over neighborhood
      feature vectors via pgvector, semantic nearest-neighbor search
- [ ] Select generation model — retrieval/data quality matters more than
      model choice; any competent instruction-following model is sufficient
- [ ] Cap and monitor per-request LLM cost (per Cost Constraints in
      `PROJECT.md`)

### Deliverables

- NL query → structured filter → ranked results flow
- Score explanation generation wired to the explanation endpoint
- Similar-neighborhoods semantic search over pgvector embeddings

### Exit criteria

A user can type a free-text query and get back addresses that match their
intent, each with a generated explanation grounded entirely in retrieved
data (no unsupported claims about amenities that aren't in the feature
store).

---

## Phase 4 — Feature Expansion (post-MVP)

**Goal:** Extend the product only once there's traction signal justifying
the added complexity/cost.

**Dependencies:** Phases 1–3 complete and in production with real usage.

### Tasks

- [ ] **Commute-aware scoring** — actual workplace → commute time via GTFS
      + routing engine (not generic "near transit")
- [ ] **Budget/rent overlay** — cross-reference score with rent/price data
- [ ] **Side-by-side comparison** — 2–3 addresses on the same factor
      breakdown
- [ ] **Multi-metro expansion**:
  - [ ] Only at this point, consider Airflow (multiple refresh cadences
        across metros justifies an orchestrator)
  - [ ] Only at this point, consider paid Places API for coverage gaps OSM
        can't fill

### Deliverables

- Feature(s) built are driven by observed usage signal, not speculative
  roadmap — pick from the above based on what traction data actually shows

### Exit criteria

N/A until traction signal exists — this phase is intentionally not
scheduled until Phases 1–3 are live and generating real usage data.

---

## Cross-Phase Sequencing Notes

(See `PROJECT.md` → Build Sequencing Guidance for full rationale.)

- Phase 0 is single-owner, sequential, first.
- Within Phase 1, ingestion scripts (OSM, GTFS per agency, schools, roads)
  are independent and parallelizable once Phase 0 schema is locked.
- Valhalla setup (Phase 2) is independent infra and can start in parallel
  with Phase 1 ingestion work.
- Frontend scaffolding can start early against a mocked API response.
- Scoring engine design stays direct work — not delegated — since it's
  where product judgment and defensibility live.
- API integration + RAG layer (Phase 3) is sequential, after scoring and
  isochrone services exist.
