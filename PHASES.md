# BenriSpace — Phase Breakdown

Detailed breakdown of each build phase from `PROJECT.md`. This file expands
each phase into concrete tasks, deliverables, and exit criteria. See
`PROJECT.md` for overall architecture, scoring factors, and business context.

Each phase below has a **Requirements from you** subsection — accounts,
API keys, or decisions that only you can provide, not something to design
around. Full list, but here's what's actually blocking right now:

## Blocking Phase 1 today

All the code that *doesn't* need these has been built and unit-tested
(grid, POI/transit/schools/roads/airports ingestion, scoring engine, API
scaffold — see Phase 1's Tasks below for the detailed state of each). What's
below is genuinely blocking the next step for each:

- [x] Register `benrispace.com` — done 2026-09-28. DNS records themselves
      come later (Firebase/Cloud Run each issue their own once set up —
      see the domain note under Requirements below); nothing to configure
      on the domain yet.
- [ ] GCP account with billing enabled + a project for this app — blocks
      deploying the (already-built) API to Cloud Run
- [ ] Confirm access to the existing Firebase Hosting project — blocks
      wiring up the frontend
- [ ] Supabase project (Project URL, anon key, service role key, Postgres
      connection string) — blocks running any of the built ingestion jobs,
      the scoring engine, or the ingestion GitHub Actions workflow against
      real data; also blocks the API actually returning results
- [ ] NJ Transit developer API key — blocks that one agency only; MTA/LIRR/
      Metro-North transit ingestion is otherwise code-complete

Everything else (Valhalla hosting in Phase 2, LLM provider in Phase 3,
Google OAuth + Stripe in Phase 4) is deferred and detailed in its own
phase's Requirements section below.

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

- [~] **Register benrispace.com** and point DNS — domain registered
      2026-09-28. DNS records (`benrispace.com`/`www.benrispace.com` →
      Firebase Hosting, `api.benrispace.com` → Cloud Run) come from those
      two services once each is set up (Firebase's custom-domain flow and
      Cloud Run's domain-mapping flow both generate their own records to
      add) — not something to configure yet, tracked as still-open below.
- [x] **Grid generation** (not originally listed as its own task — a gap
      found while building: every ingestion job below writes into
      `feature_store` keyed by `geo_entity_id`, so those rows have to exist
      first) — `ingestion/grid.py`, geohash6 grid over the v1 metro bounding
      boxes, ~64,300 cells. Logic verified directly (no DB needed); DB write
      path untested (no live Postgres in this sandbox).
- [x] **POI ingestion (OSM Overpass)** — `ingestion/osm_poi.py`. Code
      complete + unit tested (24 tests); not yet run against a live DB.
- [~] **Transit ingestion (GTFS static)** — `ingestion/gtfs_transit.py`,
      shared parser + per-agency config, degrades gracefully per-agency:
  - [x] MTA — code complete, feed URLs verified live
  - [x] LIRR — code complete, feed URLs verified live
  - [x] Metro-North — code complete, feed URLs verified live
  - [ ] NJ Transit — cleanly stubbed (raises with a message pointing here);
        blocked on the developer API key below, and its username/password
        auth flow (not a static zip like the others) still needs
        implementing once that key exists
- [~] **School data ingestion** — `ingestion/schools.py`, pluggable
      `SchoolDataSource` interface:
  - [x] NYC Open Data — code complete, **verified live** (1,899 schools
        fetched, real query results sanity-checked)
  - [ ] Nassau/Suffolk, Westchester — stubbed behind the same interface
        (`NotImplementedError`, `# TODO: verify current dataset URL`), not
        wired up
  - [ ] Northern NJ, Fairfield CT — no source built yet
- [x] **Road classification ingestion** — `ingestion/roads.py`. Code
      complete + unit tested (18 tests) for `road_classification`,
      `congestion_proxy_raw`, `emergency_corridor_proxy_raw`,
      `street_orientation`.
- [x] **Airport proximity** — `ingestion/airports.py`. JFK/LGA/EWR
      hardcoded; drive time via a pluggable router — straight-line fallback
      active today (Valhalla unset), real Valhalla call wired and ready for
      the moment Phase 2 lands (one-place swap via `VALHALLA_URL`).
- [x] **Trail popularity ingestion** — user-requested addition (2026-09-28):
      Strava/Garmin/popular running trails as a proxy for popularity,
      desirable neighborhood, and safety. `ingestion/trails.py`: OSM
      trail/path tags (free, required baseline — `running_trail_count_800m`/
      `running_trail_nearest_m`) + Strava Segments API popularity
      (`strava_segment_count_800m`/`strava_segment_popularity_raw`,
      optional — degrades to OSM-only when unconfigured, same pattern as
      NJ Transit). Garmin dropped — no suitable public API found (see
      `PROJECT.md`). Strava is tightly rate-limited (~100/15min, ~1000/day):
      `GET /segments/explore` doesn't carry popularity fields, so a
      two-stage explore-then-detail-call pipeline is required — tiled at
      227 explore calls + up to ~673 detail calls across the metro, ~150
      minutes worst-case, fine for the weekly cron, not something a live
      request ever waits on. Code complete + unit tested (45 tests,
      pure/mocked, no live Strava/DB calls); the CI workflow's 180-minute
      timeout accounts for Strava's worst case. Contracts, `scoring/
      engine.py` (`trail_popularity_score`, weight 1.25), and this
      ingestion script are all done — 156 tests passing project-wide.
- [x] **Ingestion orchestration** — `.github/workflows/ingestion.yml`:
      grid → ingestion jobs in parallel (`fail-fast: false`, so a missing
      NJ Transit key or unconfigured Strava doesn't block the others) →
      scoring, weekly cron + manual dispatch. **Inert until `DATABASE_URL`
      is a repo secret** (see Requirements below) — written and
      YAML-validated, not yet run. Needs `ingestion.trails` added to the
      matrix once that script lands.
- [ ] **Storage** — Supabase free tier (Postgres + pgvector). Not started —
      blocked on you creating the project (see Requirements below). A local
      Postgres+pgvector (`docker-compose.yml`) stands in for dev, but
      nothing has run against *any* live Postgres yet — this sandbox has no
      Docker either.
- [x] **Scoring engine** — `scoring/engine.py` + `scoring/run.py`. Weighted
      composite of normalized sub-scores, hand-tuned weights with
      documented rationale, 8 unit tests. Kept as direct (non-delegated)
      work per this phase's own sequencing guidance.
- [~] **API** — `api/` implements all three `contracts/openapi.yaml`
      endpoints (unauthenticated — Phase 4 adds auth on top), 92 unit
      tests. `GET /score` is fully real; `/explanation` and `/triangulate`
      are clearly-labeled Phase 1 placeholders (template-based explanation,
      straight-line-circle isochrone) standing in for Phase 3/2. Uses OSM
      Nominatim for address geocoding — a new design call, not previously
      specified, flagged for your review. **Not yet deployed** — blocked on
      Cloud Run/GCP access below.
- [ ] **Frontend** — point existing Firebase Hosting setup at the new API.
      Not started — this repo has no Firebase config, so the existing
      frontend lives elsewhere; blocked on you confirming that project
      (see Requirements below).

### Deliverables

- Populated feature store for the full v1 metro radius
- Precomputed composite + sub-scores for all addresses/geohashes in scope
- Live API serving score + explanation data
- Frontend displaying scores for a searched address

### Exit criteria

A user can search an address in the NYC metro radius and get back a
composite score with sub-factor breakdown, sourced entirely from
precomputed data (no live third-party API calls on the request path).

### Requirements from you

Nothing in this phase can start until these exist — none of it is a design
decision, it's just accounts/credentials only you can create:

- **Domain**: registered 2026-09-28. Nothing else needed on this yet —
  DNS records get added once Firebase Hosting and Cloud Run domain
  mappings exist (each generates its own records/verification steps; I
  can't specify them ahead of those services existing). When that step
  comes, either hand me registrar/DNS login or add the records I give you
  yourself — your call.
- **GCP**: an account with billing enabled (required by Cloud Run even on
  the free tier — card on file, not an expected charge), a project for this
  app, and either a service-account key or Workload Identity Federation
  setup with Cloud Run deploy permissions for GitHub Actions.
- **Firebase**: confirm the project ID/console access for the "existing
  Firebase Hosting setup" `PROJECT.md` refers to, so the custom domain and
  new API can be wired into it.
- **Supabase**: create a free-tier project, then give me the Project URL,
  anon public key, service role key (server/CI secret only — never ships to
  the frontend), and Postgres connection string.
- **GitHub Actions secrets**: repo is confirmed at
  `github.com/prajeshgpat/BenriSpace` — add `SUPABASE_SERVICE_ROLE_KEY` and
  the GCP deploy credentials above as repo secrets once created.
- **NJ Transit developer account + API key** — their GTFS static feed
  requires registration, unlike MTA/LIRR/Metro-North which are open
  downloads with no key.
- *(Optional, not blocking)* **Strava API application** — for real trail
  popularity data (athlete/effort counts), register at
  `strava.com/settings/api` and give me the Client ID, Client Secret, and
  an OAuth refresh token with `read` scope (your own account authorizing
  the app is fine — this only reads public segment data, not personal
  activity). Trail ingestion works without this via OSM trail data alone;
  Strava adds the actual "popularity" signal on top. No equivalent exists
  for Garmin — dropped from scope, see `PROJECT.md`. Worth knowing before
  you set this up: Strava's rate limits make the enhancement take up to
  ~150 minutes per weekly run, which on a private GitHub repo eats real
  Actions minutes (~600/month against the free-tier budget) — a real,
  if modest, cost tradeoff against the $0/month target.
- *(Optional, not blocking)* a NYC Open Data / Socrata app token, only if
  anonymous rate limits become a problem.

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

### Requirements from you

- **Where Valhalla runs — deferred by you to this phase.** Two live
  options, revisit when we get here:
  - Free GCP e2-micro VM in the same project as Cloud Run (keeps the stack
    on one vendor at $0/month, but e2-micro's RAM may be tight for the
    NYC-metro OSM extract — needs a real test, not an assumption)
  - A small paid VM (DigitalOcean/Linode/Fly.io, ~$5–6/mo) with more
    headroom
  Whichever you pick, I'll need that provider's account + API key or SSH
  access to provision it.

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

### Requirements from you

- **LLM provider — deferred by you to this phase.** Revisit when we get
  here: Anthropic or OpenAI, and I'll need an API key from that provider's
  console plus a spending cap/budget alert configured on the account
  (per Cost Constraints in `PROJECT.md`).

---

## Phase 4 — Auth, Tiers & Billing

**Goal:** Move from open/single-tenant access to Google sign-in with three
priced tiers (Free, Pro, Business), enforced request limits, and self-serve
billing — while staying near-$0/month until paid conversions justify the
spend. See `PROJECT.md` → Access Model & Scaling Path for full rationale.

**Dependencies:** Phases 1–3 working end-to-end (there must be a product
worth gating before gating it).

**No retrofit of Phase 0/1 schema.** `geo_entities`, `feature_store`, and
`scores` are shared reference data with no user ownership — they need no
changes here. All new tables in this phase are additive.

### Tasks

- [ ] **Auth** — Google sign-in via Supabase Auth (same Supabase project
      already running Postgres/pgvector; no new vendor)
- [ ] **Schema additions** (additive, not a migration of Phase 0/1 tables):
  - [ ] `accounts` — maps to Supabase `auth.users`, holds `tier`,
        `stripe_customer_id`
  - [ ] `api_keys` — Business-tier programmatic access, hashed key storage,
        account-scoped
  - [ ] `usage_counters` — per-account, per-period request counts, for both
        quota enforcement and billing metering
  - [ ] Enable row-level security on all account-scoped tables from their
        first row
- [ ] **Define tier limits** (initial values, tune as usage data comes in):
  - [ ] Free — 50 score lookups/day, 10 triangulations/day, no NL/RAG query
        access, web UI only
  - [ ] Pro — ~2,000 score lookups/day, 200 triangulations/day, 100 NL/RAG
        queries/day, saved anchors, web UI only
  - [ ] Business — API key/programmatic access, custom/negotiated volume +
        usage-based overage
- [ ] **Rate limiting** — FastAPI middleware checks `usage_counters` against
      tier limits before touching the feature store; `429` + `Retry-After` +
      upgrade prompt on over-limit (start with a Postgres counter check, not
      Redis — only move to Redis/Upstash if request volume itself makes the
      DB round-trip the bottleneck)
- [x] **API contract addition (non-breaking)** — add auth header/security
      scheme and `429` response schema to Phase 0's `contracts/openapi.yaml`
      (`bearerAuth`/`apiKeyAuth` security schemes, `401`/`429` responses,
      `X-RateLimit-*` headers on success responses, all three endpoints)
- [ ] **Billing** — Stripe Checkout + Customer Portal for self-serve
      Free→Pro upgrade; Business tier stays sales-assisted/manually invoiced
      until there's demand for self-serve
- [ ] **Frontend** — sign-in flow (Supabase Auth JS client), account/billing
      settings page, usage dashboard so users can see their own quota usage

### Deliverables

- Google sign-in working end-to-end
- `accounts` / `api_keys` / `usage_counters` schema with RLS policies
- Tier limits enforced in API middleware
- Stripe self-serve Free→Pro upgrade
- Usage dashboard in frontend

### Exit criteria

A new user can sign in with Google, land on Free tier, hit their daily
quota and get a clear `429` + upgrade prompt, self-serve upgrade to Pro via
Stripe Checkout, and see higher limits apply immediately.

### Requirements from you

- **Domain email for benrispace.com** — needed for both items below. If you
  don't already have email hosting on the domain (Google Workspace,
  Cloudflare Email Routing, or similar forwarding), set that up before this
  phase starts; a `support@benrispace.com`-style address is what goes on
  the OAuth consent screen and the Stripe account.
- **Google Cloud Console OAuth client** (separate from the GCP project
  hosting Cloud Run, or the same one — your call): configure the OAuth
  consent screen (app name "BenriSpace", the support email above), then
  create an OAuth 2.0 Client ID + Secret with:
  - Authorized JavaScript origin: `https://benrispace.com`
  - Authorized redirect URI: your Supabase project's
    `https://<project>.supabase.co/auth/v1/callback`
  Hand me the Client ID + Secret to enter into Supabase Auth's Google
  provider config.
- **Stripe account**: publishable key + secret key (test mode is enough to
  build against), a Product/Price created for the Pro tier (monthly), and a
  webhook signing secret. Before accepting real payments (not needed to
  build the integration), Stripe also requires legal business name/ID and a
  bank account for payouts to activate live mode.

---

## Phase 5 — Feature Expansion (post-MVP)

**Goal:** Extend the product only once there's traction signal justifying
the added complexity/cost.

**Dependencies:** Phases 1–4 complete and in production with real usage.

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
scheduled until Phases 1–4 are live and generating real usage data.

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
- Auth/billing (Phase 4) starts after Phases 1–3 work end-to-end — sign-in
  and tiering only matter once there's a product worth gating. Sign-in UI
  can be scaffolded early against a mocked account, same as frontend
  scaffolding against a mocked API response. It adds new account-scoped
  tables only — no retrofit of the Phase 0/1 schema, since that data has no
  user ownership to begin with.
