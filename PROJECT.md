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
| Popular running/walking trails (proxy for popularity, desirable neighborhood, safety) | Positive | OSM trail/path tags (free, required) + Strava Segments API popularity (optional enhancement, requires app registration) |

OSM alone only tells us a trail *exists*, not that it's *popular* — Strava's
segment data (athlete/effort counts) is the actual popularity signal named
above; OSM trail presence is the fallback baseline when Strava isn't
configured. **Garmin was considered and dropped**: unlike Strava, Garmin has
no public API exposing aggregate trail/route popularity data (its developer
program is oriented around an individual athlete's own device/health data,
not public usage aggregates) — noted here so it isn't silently forgotten as
"still pending," it's a deliberate scope call, flag if you know of an
access path we're missing.

Scores are a **weighted composite of normalized sub-scores**, hand-tuned
initially (no training data to fit against yet). Document weight rationale —
it's the defensibility story for both users and future ML refinement.

---

> System diagrams (runtime, data pipeline, data model, delivery): see
> [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Hosting & Domain

Production domain: **benrispace.com** (registered 2026-09-28). DNS
stays at **Cloudflare** (the domain is registered at Cloudflare Registrar,
which requires Cloudflare nameservers) and Terraform manages every record
through the Cloudflare provider — Amplify, the API custom domain and ACM
certificate validation — as DNS-only records so AWS certificates validate
end to end.

- `benrispace.com` / `www.benrispace.com` → frontend (**Next.js +
  TypeScript on AWS Amplify Hosting**)
- `api.benrispace.com` → backend API (**AWS Lambda behind API Gateway HTTP
  API**)
- **Cloud vendor: AWS, everything** (backend switched from GCP 2026-09-29;
  frontend moved off Firebase Hosting the same day for a single-cloud
  stack — see rationale below). Valhalla is just a self-hosted Docker
  container, so it isn't tied to any particular cloud; it co-locates on a
  small EC2 instance in the same account.
- **Infrastructure-as-code: Terraform** for every AWS resource (Lambda, API
  Gateway, IAM + GitHub OIDC deploy role, Amplify app, Cloudflare DNS records, ACM
  certs, later EC2 for Valhalla), under `infra/`. State lives in an S3
  backend. Nothing is click-configured in the console — the whole stack is
  reproducible from the repo, which is the production-readiness story
  and a major resume signal (IaC is among the most-requested skills in
  both SWE and data-engineering postings).
- **CI/CD: GitHub Actions**, unchanged — ingestion cron plus deploy
  workflows. Airflow/Dagster stay deferred per Phase 5.
- **API compute: AWS Lambda** (via the Mangum ASGI adapter, no FastAPI
  code changes needed) fronted by **API Gateway HTTP API**, not App Runner
  or Fargate — Lambda genuinely scales to zero and its free allowance (1M
  requests + 400,000 GB-s/month) is one of AWS's always-free offers. A
  bare Lambda Function URL was the earlier plan, but Function URLs don't
  support custom domains, so `api.benrispace.com` needs API Gateway (or
  CloudFront) in front; API Gateway HTTP API is the more standard,
  recognizable choice and costs ~$1 per million requests past any free
  allowance — effectively $0 at this traffic.
- **Frontend: Next.js + TypeScript on Amplify Hosting** — React/TypeScript
  is the most in-demand frontend skill set, and Amplify gives Firebase-like
  git-push deploys and per-branch preview URLs while keeping the stack
  single-cloud. Lives in `web/` in this repo.
- **Why AWS over GCP**: not a cost decision (both clouds' free tiers are
  comparable at this scale) — AWS has broader generic market/resume
  recognition across job postings than GCP, which matters given this
  project doubles as a portfolio piece (see Overview). GCP was an equally
  legitimate technical choice; this was a deliberate trade against
  resume breadth once the Valhalla co-location constraint (the original
  reason for picking GCP) turned out not to actually require GCP.
- See `PHASES.md` for the concrete accounts/keys/DNS records needed to wire
  this up, phase by phase.

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
- **Trails**: OSM-tagged running/walking paths (free, no key, required
  baseline) + Strava Segments API popularity data (optional enhancement,
  requires a Strava API app — see Phase 1 Requirements in `PHASES.md`).
  Garmin has no suitable public API for this and isn't pursued.
- **Ingestion orchestration**: GitHub Actions scheduled workflow — sufficient
  for weekly/monthly refresh cadence. Do not reach for Airflow yet; it's
  unnecessary operational overhead at this scale.
- **Storage**: Supabase free tier (Postgres + pgvector included — same
  instance serves the embeddings work in Phase 3, no separate vector DB
  needed)
- **Scoring**: precomputed and stored, never calculated live per request.
  This is the key scalability lever — it keeps live user traffic from ever
  touching rate-limited third-party APIs.
- **API**: FastAPI on AWS Lambda (Mangum ASGI adapter) behind API Gateway
  HTTP API — scales to zero when idle — served at `api.benrispace.com`
- **Frontend**: Next.js + TypeScript on AWS Amplify Hosting, served at
  `benrispace.com`/`www.benrispace.com` (replaces the earlier Firebase
  Hosting plan)
- **Infrastructure**: Terraform (`infra/`) provisions all AWS resources;
  GitHub Actions deploys via an OIDC-assumed IAM role (no long-lived AWS
  keys in repo secrets)

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

### Phase 4 — Auth, Tiers & Billing

- **Auth**: Google sign-in via Supabase Auth — same Supabase project already
  running Postgres/pgvector, no new vendor. Google-only is sufficient for v1;
  don't build email/password until there's a reason to.
- **Multi-tenancy, added not retrofitted**: `geo_entities` / `feature_store` /
  `scores` (Phase 0) are shared reference data, not user-owned — they need no
  account scoping. New tables only: `accounts` (maps to Supabase
  `auth.users`, holds `tier`, `stripe_customer_id`), `api_keys` (Business tier
  programmatic access — hashed key storage, account-scoped), `usage_counters`
  (per-account, per-period request counts for quota enforcement + billing
  metering).
- **Row-level security**: enable Postgres RLS on the new account-scoped
  tables from day one. Cheap to add now with near-zero rows; expensive to
  retrofit once there's real user data.
- **Three tiers** — Free, Pro, Business:
  | Tier | Access | Initial limits (tune as usage data comes in) | Billing |
  | --- | --- | --- | --- |
  | Free | Web UI only | 50 score lookups/day, 10 triangulations/day, no NL/RAG queries | none |
  | Pro | Web UI only | ~2,000 score lookups/day, 200 triangulations/day, 100 NL/RAG queries/day, saved anchors | self-serve, Stripe Checkout |
  | Business | API key, programmatic | Custom/negotiated volume + usage-based overage | sales-assisted initially (manual invoicing) — this is the API-first licensing product from the Business Model section below, not a new idea |
- **Rate limiting**: enforce tier limits in FastAPI middleware against
  `usage_counters` before touching the feature store — a cheap Postgres
  counter check is fine at low volume; only move to Redis/Upstash if request
  volume makes the extra DB round-trip the actual bottleneck. Over-limit
  requests get `429` + `Retry-After` and an upgrade prompt, not a silent
  drop.
- **API contract addition (non-breaking)**: Phase 0's `openapi.yaml` gets an
  auth header/security scheme and a `429` response added here — this is an
  addition to the existing contract, not a redesign of it.
- **Business tier stays sales-assisted at first**: don't build self-serve
  Business billing/onboarding before there's demand for it — with "a few
  users," manual invoicing is cheaper than building infrastructure for a
  motion that doesn't exist yet.

### Phase 5 — Feature Expansion (post-MVP, only with traction signal)

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
- **Auth/billing (Phase 4)**: starts after Phases 1–3 work end-to-end — sign-
  in and tiering only matter once there's a product worth gating. Sign-in UI
  can be scaffolded early against a mocked account, same as frontend
  scaffolding against a mocked API response.

---

## Development Workflow

All work happens on the **`dev-benrispace`** branch. `main` changes only
through a pull request, because merging to `main` is what costs money and
risk: it triggers the Amplify frontend build and the Lambda deploy workflow.

1. Commit to `dev-benrispace` and push. `ci.yml` runs on every push: it
   diffs against `main`, then runs the Python lint + tests and/or the web
   lint + typecheck + tests + production build, only for the areas that
   changed. A docs-only branch runs almost nothing; a newer push cancels an
   in-flight run.
2. Open a PR `dev-benrispace` → `main`. `ci.yml` and (for `infra/**`)
   `terraform.yml` run again; **`ci-ok`** is the single status to require
   before merging.
3. Merge. Only now do `deploy-api.yml` (API/common/scoring/pyproject
   changes) and the Amplify build (every push to `main`) run. Batching
   several small changes into one PR means one deploy instead of many.
4. Infrastructure: edit `infra/` on the dev branch, merge, then run
   `terraform apply` locally (AWS SSO) — apply is deliberately manual.

---

## Business Model

Leaning **API-first/licensing**, not a consumer-facing app as the primary
revenue path: sell the convenience/triangulation score to real estate
platforms, relocation companies, brokerages, and multifamily marketers.
Closest comp is Walk Score's licensing model (historically embedded on
Redfin/Zillow listings). The consumer-facing app is more valuable right now
as a demo/portfolio piece than as a standalone product — build it as the
front door that gets B2B conversations started, not as the end goal.

The three-tier model (Phase 4) is how this plays out concretely: **Free/Pro
are the consumer front door** described above, generating usage data and
portfolio credibility. **Business tier — API-key programmatic access — is
this section's actual revenue path**, sold to the platforms/brokerages/
marketers this section names, not a separate idea layered on top.

---

## Access Model & Scaling Path

Designed for **1 to a few users today, without a rebuild when it grows**:

- **Auth**: Google sign-in via Supabase Auth (Phase 4) — reuses the existing
  Supabase project, no new vendor to operate at low volume.
- **Multi-tenancy without retrofitting the data layer**: the Phase 0/1
  schema (`geo_entities`, `feature_store`, `scores`) is shared reference
  data with no user ownership, so it needs no changes for auth to land.
  Account-scoped tables (`accounts`, `api_keys`, `usage_counters`) are added
  fresh in Phase 4, with row-level security enabled from their first row —
  cheap now, expensive to bolt on after there's real user data.
- **Free-tier request limits exist to protect the cost budget below**, not
  just to segment pricing: without a cap, one bot or one enthusiastic script
  could drive the "$0/month" infra into a paid tier before there's any
  revenue to justify it.
- **Rate limiting starts as a Postgres counter check** in API middleware —
  adequate at low request volume. Swap to Redis/Upstash only when request
  volume itself (not user count) makes that extra DB round-trip the
  bottleneck; don't provision it ahead of that signal.
- **Business tier stays sales-assisted/manually invoiced until there's
  demand for self-serve** — building automated onboarding for a motion with
  zero customers is pure waste; Free/Pro get Stripe self-serve because that
  volume can actually show up on day one.

---

## Cost Constraints

Phase 1 should run close to **$0/month**, with a few small, known line
items: Supabase free tier, Lambda's always-free allowance (1M requests +
400,000 GB-s/month), GitHub Actions free minutes, OSM/GTFS/NYC Open Data
all free. Real, non-$0 items to plan for:

- **Domain registration** for benrispace.com (~$12–20/yr depending on
  registrar).
- **DNS**: free — Cloudflare hosts it, so no Route 53 zone.
- **Terraform state**: an S3 bucket holding a few KB — effectively $0.
- **API Gateway HTTP API**: ~$1 per million requests — pennies at this
  traffic.
- **Amplify Hosting**: charged per build-minute and GB served; small for a
  low-traffic site, but not an always-free service.
- **AWS free tier caveat — verify at signup.** AWS restructured its free
  tier for *new* accounts in mid-2025: instead of the old 12-months-free
  model for services like EC2 and Amplify, new accounts get a starting
  credit balance on a time-limited free plan, while a set of
  "always free" offers (Lambda's allowance among them) continue
  indefinitely. The exact credit amounts and terms change — check the
  current AWS Free Tier page when creating the account rather than
  trusting this doc. Practical upshot: Lambda stays free long-term; EC2
  (Valhalla, Phase 2) and Amplify draw down credits and then bill
  normally, so budget a few dollars a month for them after credits run
  out.
- **AWS requires a card on file to create an account at all** — not an
  expected charge, just a signup requirement. Set up an **AWS Budgets
  alert** (e.g. $10/month) on day one so an unexpected bill can't sneak
  up; that's in the Terraform scope too.

The only realistic *variable* early cost is LLM API calls in Phase 3 — keep
these capped and per-request cheap; don't add paid data sources (e.g. Google
Places) until free sources prove insufficient with real usage data to
justify the spend.

Phase 4 (auth/billing) also stays near-$0 at low volume: Supabase Auth's
free tier covers a generous monthly-active-user count, and Stripe has no
monthly fee — only a per-transaction cut on actual revenue, so it's
self-funding rather than a new fixed cost.
