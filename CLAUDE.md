# BenriSpace

Scores how convenient any place in the New York metro (NY, NJ, CT) is, out of 100, from 13 factors.
Live at benrispace.com (Next.js on Amplify) and api.benrispace.com (FastAPI on Lambda), data in
Supabase Postgres + PostGIS, static score/area files and tiles on Cloudflare R2. See README.md for
features and docs/ARCHITECTURE.md for the system design.

## Repo map

- `web/`: Next.js 15 / React 19 / TypeScript / MapLibre. Vitest unit tests, Playwright E2E in `web/e2e/`
- `api/`: FastAPI routes, chat, explanations, MCP server (`api/mcp.py`), Lambda handler
- `scoring/`: engine, per-area density scoring (`area_run.py`, `density.py`), scales, similarity
- `ingestion/`: one module per data source, plus `areas/` (polygon builder) and `routing/`
- `common/`: DB layer, Overpass client, LLM client (`llm.py`), geo and unit helpers
- `contracts/`: `openapi.yaml` (source of truth for the API), `schema.sql`, numbered `migrations/`
- `infra/`: Terraform for AWS and Cloudflare
- `docs/`: ARCHITECTURE, SCORING, ROADMAP, PLANNED, DATA_PLATFORM (target pipeline), api, data-sources

## Commands

```bash
# Python (repo root, .venv)
ruff check .
pytest -q                          # no database needed; route tests use fake connections
.venv/bin/uvicorn api.main:app --port 8000   # no --reload: restart after api/ changes

# Web (in web/, Node 24 per web/.nvmrc; Next 15 will not run on older Node)
npm run check                      # lint + typecheck + vitest + build (what CI runs)
npm run dev                        # http://localhost:3000
npm run generate:api               # regenerate src/lib/api/schema.d.ts after editing contracts/openapi.yaml
npx playwright test                # E2E against a mocked API

# Infra
cd infra && terraform fmt -recursive && terraform validate
```

Local Postgres: `docker compose up db` (Docker runs on Colima; `colima start` after a reboot).

## Workflow

- Work on `dev-benrispace`. Never commit or push to `main`, including docs-only changes.
- Changes reach `main` only via a PR from `dev-benrispace`; the owner merges it. Merging deploys
  (Amplify on every push to main; `deploy-api.yml` when api/common/scoring/pyproject change), so batch
  work into one PR.
- Run `ruff check .`, `pytest -q` and `npm run check` before pushing.
- Terraform: edit on the branch, merge via PR, then the owner runs `terraform apply` locally (AWS SSO).

## Conventions

- **Imperial units everywhere**: ft, mi, sq mi, mph, minutes, in DB columns, constants, API fields,
  UI text and explanations. When touching metric leftovers, plan their rename.
- A missing measurement is `null` / "No data", never 0.
- Densities and place counts are internal only; never show them to users.
- The LLM (Claude Haiku via `common/llm.py`) only narrates or parses retrieved data; it never invents
  numbers. Budget is about $5/month with a kill switch, so keep token caps and caching intact.
- API changes start in `contracts/openapi.yaml`; schema changes are a new numbered migration in
  `contracts/migrations/` (latest is 0023), mirrored in `schema.sql`.
- Update README.md and the relevant docs/ file when shipped behavior changes.

## Data and production safety

- Production scores come from the `v2.2-density` model. The weekly GitHub Actions ingestion does NOT
  recompute it; the routing and area scoring refresh runs locally about monthly (see
  docs/ARCHITECTURE.md section 2).
- Routing and scoring jobs (`ingestion.routing.*`, `scoring.area_run --write`) write to `DATABASE_URL`.
  Run them against the local Docker db and copy results to prod (`scripts/copy_routing.py`); never
  point `DATABASE_URL` at prod unless a prod write is intended and approved.
- Ask before applying migrations or any other write to the production database.
- Full ingestion hits public OpenStreetMap servers (~45 min); run it sparingly.
- Secrets live in `.env` (gitignored) and AWS SSM; never commit or print them.
