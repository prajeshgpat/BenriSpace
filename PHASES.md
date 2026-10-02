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

- [x] Register `benrispace.com` — done 2026-09-28 (at Cloudflare
      Registrar; see the DNS decision below).
- [ ] AWS account with billing enabled — blocks `terraform apply` and
      therefore every deploy (API, frontend, DNS). **Switched from GCP
      2026-09-29** — see `PROJECT.md` → Hosting & Domain for rationale
      (resume breadth, not cost). Nothing GCP-specific was ever built, so
      this was a clean swap, not a migration. Terraform config and the
      Next.js frontend can both be written *before* the account exists;
      only applying/deploying needs it.
- [x] **Cloudflare API token** — done 2026-10-01 (rolled once after it
      appeared in chat). Lives in `~/.cloudflare_token` (mode 600, outside
      the repo); Terraform reads it from `CLOUDFLARE_API_TOKEN`.
- ~~Confirm access to the existing Firebase Hosting project~~ — no longer
      needed: the frontend moves to Next.js on Amplify (2026-09-29). If the
      existing Firebase-hosted frontend has code worth porting (components,
      styling, copy), point me at that repo — optional, not blocking; the
      default is to build `web/` fresh.
- [x] **Supabase — fully unblocked 2026-09-29.** Project created, schema
      applied, and the full pipeline verified live: grid generation
      (64,320 cells), airport ingestion, scoring, and `GET /score` all ran
      against real Supabase data and produced correct results — this
      project's first real (non-mocked, non-unit-test) end-to-end proof.
      Caught and fixed a real bug in the process: every ingestion script
      was doing ~64k unbatched network round-trips per run (>3 minutes and
      still hadn't written a single row); `common/db.py`'s `get_connection`
      now wraps every connection in psycopg3 pipeline mode, which dropped
      airport ingestion to 5.9 seconds for all 64,320 rows. This benefits
      every ingestion script, not just airports, automatically (no changes
      needed to any of them). Note: used the **Session pooler** connection
      string, not the direct-connection host — that one is IPv6-only by
      default and failed to resolve from this sandbox (no outbound IPv6),
      which would also fail on GitHub Actions runners (IPv4-only), so the
      pooler is the right production choice too, not just a workaround.
      Only `airports.py` and `scoring/run.py` have been run against real
      data so far — the OSM/GTFS/NYC-Open-Data/Strava-backed jobs
      (`osm_poi`, `gtfs_transit`, `schools`, `roads`, `trails`) haven't
      been run live yet; they make real external API calls, some
      (`trails.py`'s Strava path) with real rate-limit-bound runtimes, so
      that's worth a deliberate go-ahead rather than doing it silently.
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
      2026-09-28 at Cloudflare Registrar. DNS stays at Cloudflare; Terraform
      (Cloudflare provider) owns every record — `benrispace.com`/`www` →
      Amplify, `api.benrispace.com` → API Gateway, and ACM certificate
      validation. **Live 2026-10-02**: `api.benrispace.com`,
      `benrispace.com` and `www.benrispace.com` all resolve and serve over
      valid Amazon certificates (DNS-only records).
- [~] **Infrastructure-as-code (Terraform)** — `infra/` (+ `infra/bootstrap/`
      for the S3 state bucket). **Stage 1 applied 2026-10-01** (AWS account
      `812960096894`, us-east-1): state bucket, Lambda `benrispace-api`,
      API Gateway HTTP API (throttled 10 rps / burst 20), SSM SecureString
      for the database URL (set out-of-band; never in state), GitHub OIDC
      deploy role (repo + `main` only), $10/month budget alert to
      prajeshgpat@gmail.com. The live API returns real scores (Midtown
      Manhattan: composite 76.6, all 11 factors, ~0.2s warm), CORS allows
      only the frontend origins. **Stage 2 applied 2026-10-02**: ACM
      certificates, the `api.benrispace.com` custom domain, the Amplify
      app/branch/custom domain, and all Cloudflare DNS records (27
      resources total now managed). DNS stays at Cloudflare (the domain is
      registered at Cloudflare Registrar, which requires its nameservers);
      Terraform manages the records through the Cloudflare provider, all
      DNS-only so AWS certificates validate end to end. Not yet applied:
      `disable_execute_api_endpoint = true` (closing the old
      `execute-api.amazonaws.com` address), and the Valhalla EC2 instance
      (Phase 2). Operational note: the Amplify GitHub connection needed a
      classic token with **`repo` + `admin:repo_hook`** — `admin:repo_hook`
      alone (what AWS's docs state) failed with a GitHub 404 on a private
      repo even with the Amplify GitHub App installed. Keep that token
      short-lived and revoke it after use.
      Second operational note: the GitHub OIDC deploy role first rejected
      CI with `Not authorized to perform sts:AssumeRoleWithWebIdentity`
      because GitHub now issues the `sub` claim with immutable IDs
      (`repo:prajeshgpat@23436700/BenriSpace@1394007909:ref:refs/heads/main`),
      not the name-only form the trust policy assumed. Found by reading
      the failed attempts in CloudTrail (`lookup-events` on
      `AssumeRoleWithWebIdentity`); trust now matches the ID form
      (`github_owner_id` / `github_repository_id` variables), which also
      resists repo-rename/transfer impersonation.
- [~] **Lambda packaging + deploy workflow** — built 2026-09-30:
      `api/lambda_handler.py` (Mangum; loads the database URL from SSM at
      cold start, fails loudly if it can't), `scripts/build_lambda.sh`
      (cross-builds Linux arm64 / Python 3.12 wheels from any host, 9.9 MB
      zip, verified ELF aarch64 contents), `.github/workflows/deploy-api.yml`
      (test → build → OIDC deploy → smoke check). Unit tested; **the
      workflow has never run and the zip has never been invoked on Lambda**.
      Before first deploy: put `?sslmode=require&connect_timeout=5` on the
      database URL stored in SSM so a paused database fails fast.
- [x] **Grid generation** (not originally listed as its own task — a gap
      found while building: every ingestion job below writes into
      `feature_store` keyed by `geo_entity_id`, so those rows have to exist
      first) — `ingestion/grid.py`, geohash6 grid over the v1 metro bounding
      boxes. **Live-verified 2026-09-29**: 64,320 cells generated against
      real Supabase in ~3s.
- [x] **POI ingestion (OSM Overpass)** — `ingestion/osm_poi.py`. Code
      complete + unit tested (24 tests). **Live-verified 2026-09-29**:
      64,320 rows written against real Supabase (hit and recovered from a
      real Overpass 429 mid-run via the shared rate-limit backoff). Also
      received the same bucket-search fix as trails.py below (ring
      expansion instead of a brute-force fallback) — same latent bug, just
      hadn't been unlucky enough to hit it yet.
- [x] **Transit ingestion (GTFS static)** — `ingestion/gtfs_transit.py`,
      shared parser + per-agency config, degrades gracefully per-agency.
      **Live-verified 2026-09-29**: MTA (15,920 stops), LIRR (127), and
      Metro-North (114) all ingested successfully against real Supabase;
      NJ Transit correctly skipped (no key). Also fixed a real bug found
      in this run: `common/db.py` wasn't JSON-adapting the `transit_agencies`
      jsonb column, and a failure on that connection could silently corrupt
      the `ingestion_runs` bookkeeping too (both now fixed — see `common/db.py`
      and `common/ingestion_log.py`).
  - [ ] NJ Transit — cleanly stubbed (raises with a message pointing here);
        blocked on the developer API key below, and its username/password
        auth flow (not a static zip like the others) still needs
        implementing once that key exists
- [~] **School data ingestion** — `ingestion/schools.py`, pluggable
      `SchoolDataSource` interface. **Live-verified 2026-09-29**: NYC Open
      Data ingested successfully against real Supabase (64,320 rows, 1,635
      cells with a school within 1600m, avg rating 9.06/10).
  - [ ] Nassau/Suffolk, Westchester — stubbed behind the same interface
        (`NotImplementedError`, `# TODO: verify current dataset URL`), not
        wired up
  - [ ] Northern NJ, Fairfield CT — no source built yet
- [x] **Road classification ingestion** — `ingestion/roads.py`. Code
      complete + unit tested (18 tests) for `road_classification`,
      `congestion_proxy_raw`, `emergency_corridor_proxy_raw`,
      `street_orientation`. **Live-verified 2026-09-29**: 64,320 cells
      classified against real Supabase, sensible distribution (15,168
      cells with no road within 1000m, matching "unknown" orientation
      count exactly).
- [x] **Airport proximity** — `ingestion/airports.py`. JFK/LGA/EWR
      hardcoded; drive time via a pluggable router — straight-line fallback
      active today (Valhalla unset), real Valhalla call wired and ready for
      the moment Phase 2 lands (one-place swap via `VALHALLA_URL`).
      **Live-verified 2026-09-29**: 64,320 rows in 5.9s against real
      Supabase — this run is what surfaced the pipeline-mode fix below (it
      took >3 minutes and wrote zero rows before that fix).
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
      request ever waits on. Code complete + unit tested (50 tests,
      pure/mocked, no live Strava/DB calls); the CI workflow's 180-minute
      timeout accounts for Strava's worst case. Contracts, `scoring/
      engine.py` (`trail_popularity_score`, weight 1.25), and this
      ingestion script are all done — 161 tests passing project-wide.

      **Three real bugs found and fixed live (2026-09-29), running this
      against actual Supabase/Overpass data, not just unit tests:**
      (1) the per-cell bucket-index lookup fell back to a full brute-force
      scan of every segment whenever a cell's own bucket was empty — fine
      for roads (ubiquitous), pathological for trails (sparse): 4,029
      cells took 921s against real data. Fixed by expanding the search
      ring instead (same fix applied to `ingestion/osm_poi.py`, which had
      the identical latent bug, just hadn't been unlucky enough to hit it
      yet). (2) added the same Overpass-timeout quadrant-splitting
      resilience `ingestion/roads.py` already had, after a live 504 killed
      the job with no fallback. (3) the bigger one: the OSM tag selection
      was too broad — `highway=footway` with no exclusion for
      `footway=sidewalk`/`footway=crossing` was capturing ordinary
      sidewalks (present on nearly every block), not genuine trails. That
      was both *why* NYC alone returned 1,173,871 "trail" segments
      (overwhelmingly sidewalks) and a data-quality bug in its own right —
      a signal present everywhere doesn't discriminate between
      neighborhoods, defeating the point of the factor. Excluding those
      subtags (server-side in the Overpass query, not just client-side)
      dropped NYC to 326,522 segments, confirmed live.

      **Current data state**: NYC's 4,029 cells successfully landed
      (confirmed in `feature_store`) via a prior per-metro commit — proof
      the incremental-commit-per-metro design correctly preserves partial
      progress across a failed run, not just a design intent. The
      remaining 5 metros haven't landed yet: Overpass's public instance
      has been returning 504s on this query even for small split
      sub-quadrants for the last several minutes (confirmed NOT a general
      outage — trivial queries against the same server succeed instantly;
      this specific multi-clause `out geom` query is just expensive, and
      server load right now is worse than it was minutes ago when the
      identical query succeeded for all of NYC). This reads as transient
      server-side load, not a bug — retriable later (the weekly CI cron
      once secrets are wired up, or a manual re-run), not worth continuing
      to hammer a free shared public server against right now.
- [x] **Ingestion orchestration** — `.github/workflows/ingestion.yml`:
      grid → ingestion jobs in parallel (`fail-fast: false`, so a missing
      NJ Transit key or unconfigured Strava doesn't block the others) →
      scoring, weekly cron + manual dispatch (`ingestion.trails` already in
      the matrix). **Inert until `DATABASE_URL`/etc. are repo secrets** —
      YAML-validated and the underlying `common/db.py` connection path is
      now live-verified (see Storage below), but the workflow itself
      hasn't run in CI yet.
- [x] **Storage** — Supabase project live 2026-09-29 (see the Requirements
      note above for the full story: pipeline-mode fix, pooler vs. direct
      connection). Schema applied, grid populated, confirmed working
      end-to-end.
- [x] **Scoring engine** — `scoring/engine.py` + `scoring/run.py`. Weighted
      composite of normalized sub-scores, hand-tuned weights with
      documented rationale, 8 unit tests, **and now live-verified**: ran
      against real Supabase data, produced correct composite scores.
      Kept as direct (non-delegated) work per this phase's own sequencing
      guidance.
- [~] **API** — `api/` implements all three `contracts/openapi.yaml`
      endpoints (unauthenticated — Phase 4 adds auth on top), unit tested,
      with CORS for the frontend origins. `GET /score` is fully real, **and now live-verified** against
      real Supabase data via an in-process test client (not yet run as a
      deployed server). `/explanation` and `/triangulate` are
      clearly-labeled Phase 1 placeholders (template-based explanation,
      straight-line-circle isochrone) standing in for Phase 3/2. Uses OSM
      Nominatim for address geocoding — a new design call, not previously
      specified, flagged for your review. **Not yet deployed** — blocked on
      AWS access above. Lambda packaging is tracked as its own task above.
- [x] **Frontend (Next.js + TypeScript on Amplify)** — `web/`, built
      2026-09-30 and **deployed 2026-10-02** at https://benrispace.com and
      https://www.benrispace.com (Next.js 15, the newest Amplify Hosting
      supports; React 19; Node 24; first build 3 minutes). Address search →
      composite score, 11-factor breakdown (null = "No data", never 0),
      explanation; shareable `/?address=` URL; loading/validation/
      not-found/network-error states; light/dark; responsive. API types
      generated from `contracts/openapi.yaml`. Lint, typecheck, 91 unit
      tests and production build pass; golden and failure paths were
      exercised in headless Chrome against the local API. Not yet verified:
      Safari/Firefox, screen readers, real touch devices. Every push to
      `main` triggers an Amplify build (~$0.01/build-minute).

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

- **Domain**: registered 2026-09-28 at Cloudflare Registrar; DNS stays
  there. Needed: a Cloudflare API token (dashboard → My Profile → API
  Tokens → "Edit zone DNS" template, scoped to benrispace.com), exported
  as `CLOUDFLARE_API_TOKEN` in your shell — not pasted into chat or put in
  a file.
- **AWS** (switched from GCP 2026-09-29): an account with billing enabled
  (card on file required to create an AWS account at all, not an expected
  charge). Setup, in order:
  1. Create the account; turn on **MFA for the root user** and then stop
     using root for anything day-to-day.
  2. Enable **IAM Identity Center** and create yourself an admin user —
     this is what you'll use locally (`aws sso login`) to run the first
     `terraform apply`. Don't create long-lived access keys.
  3. That's it on your side — Terraform itself creates the GitHub OIDC
     identity provider and the deploy role, so CI never needs a static AWS
     key in repo secrets.
  I'll also need the AWS region you want (default recommendation:
  `us-east-1` — lowest prices and required anyway for the ACM certificate
  if CloudFront is ever added in front).
- ~~**Firebase**~~ — no longer needed; frontend moves to Next.js on
  Amplify (see Frontend task above). Optional: share the old frontend's
  repo if anything in it is worth porting.
- **Supabase — done.** Project created 2026-09-28, live and verified
  working (see "Blocking Phase 1 today" above for the full story — Session
  pooler connection string, pipeline-mode fix, everything tested against
  real data 2026-09-29).
- **GitHub Actions secrets**: repo is confirmed at
  `github.com/prajeshgpat/BenriSpace` — `.github/workflows/ingestion.yml`
  reads `DATABASE_URL` (the Session pooler connection string, same one in
  your local `.env`) plus `NJ_TRANSIT_API_KEY`/`NJ_TRANSIT_API_USERNAME`
  and the optional Strava vars. None of these are set as repo secrets yet
  — that's why the workflow is still inert despite the pipeline itself
  being live and working. Add `DATABASE_URL` as a repo secret whenever
  you're ready for the weekly ingestion cron to start running. The AWS
  deploy workflows need no AWS secret at all — just the deploy role's ARN
  (output by `terraform apply`), which is safe to store as a plain repo
  variable since OIDC does the authentication.
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

- **Where Valhalla runs — deferred by you to this phase.** Live options,
  revisit when we get here (updated 2026-09-29 for the AWS switch):
  - **Small EC2 instance in the same AWS account (recommended)** —
    provisioned by the same Terraform as everything else, keeping the
    stack single-cloud and fully IaC-managed. Two caveats: RAM may be
    tight on the smallest instance sizes for the NYC-metro OSM extract
    (needs a real test, not an assumption), and EC2 isn't an always-free
    service — under AWS's current new-account free plan it draws down
    signup credits and then bills normally (a few dollars a month for a
    small instance). See `PROJECT.md` → Cost Constraints.
  - A small VM elsewhere (DigitalOcean/Linode/Fly.io, ~$5–6/mo) — similar
    cost, but breaks the single-cloud, all-in-Terraform setup, so only
    worth it if EC2 turns out meaningfully more expensive.
  Nothing extra needed from you for the EC2 option — it rides on the AWS
  account from Phase 1.

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
- **Google Cloud Console OAuth client** — this is unrelated to AWS/hosting,
  it's specifically for "Sign in with Google" as a login provider, needed
  regardless of which cloud hosts the API. Any Google Cloud project works
  (a new one is fine, doesn't need to relate to anything else in this
  project): configure the OAuth consent screen (app name "BenriSpace", the
  support email above), then create an OAuth 2.0 Client ID + Secret with:
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
