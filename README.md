# BenriSpace

**Live site: [benrispace.com](https://benrispace.com)** · **API: [api.benrispace.com/docs](https://api.benrispace.com/docs)** · [API guide](docs/api.md)

*Benri* (便利) means "convenient". BenriSpace scores any address in the New York metro area (NYC, Long Island, Westchester, the Hudson Valley, northern New Jersey and Fairfield County, CT) on how convenient daily life is there, and shows where the convenient places are on a map. The idea: your 10-minute radius dictates your life, so see what is around any address.

**Status (October 2026).** Production serves the `v2-handtuned` model (cutover 2026-10-03, 64,320 score rows). The `v2.1-handtuned` model (13 factor pills) is built; its full ingestion is in progress and the cutover awaits owner approval. An "Ask Benri" chat is in progress. See [docs/ROADMAP.md](docs/ROADMAP.md).

## Features (shipped today)

- **Score out of 100** for any address or map click, built from the factors you choose. Production's `v2-handtuned` model has 14 factors (12 toggleable plus premium retail and running-trail popularity, which always count); `v2.1` makes all 13 factors visible pills: groceries, restaurants, cafes, bars, gym, shopping, public transit, airport, gas and convenience, traffic, schools, noise corridor and recreation. A missing measurement shows "No data", never 0.
- **Neighborhood areas.** Clicking the map outlines the area bounded by secondary-and-larger roads (at most 0.8 sq mi, 49,158 of them) and names it ("Park Slope, Brooklyn"). It falls back to the grid cell when no area fits.
- **Best areas** ranked for your factors, with numbered map markers (hover or focus one for its name and score), presets (Daily errands, Family, Commuter, Quiet) and importance sliders.
- **AI summary** of a score (Claude Haiku 4.5, grounded in that area's data only, capped at about $5/month, with a rule-based fallback).
- **Improve this area:** which nearby additions would lift weak factors, with named places.
- **Similar areas** found with pgvector embeddings.
- **Multi-stop planning** (`/v1/optimize`): near work, Trader Joe's and Planet Fitness at once, ranked by weekly travel time (openrouteservice refinement).
- **Address search** with autocomplete (LocationIQ, Photon fallback), "use my current location", readable addresses for clicked points, shareable URLs, light and dark themes, and a phone bottom-sheet layout. Distances are in feet and miles.
- **Public API**, no key needed today: [docs/api.md](docs/api.md).

Pages: Home (`/`, the explainer), the app (`/app`, search and score panel beside the map), API docs, Settings, and Pricing and Login placeholders.

Known limits: area scores average the underlying ~0.6 x 0.4 mile grid cells, so small neighbouring areas can look alike; scores are relative within each metro area; school ratings are district-level; airport and travel times are estimates until routing is precomputed.

## How it works

Scores are precomputed in batch, so the API is a thin read layer.

1. **Ingestion** pulls OpenStreetMap (Overpass), GTFS feeds (MTA, LIRR, Metro-North, PATH, NJ Transit) plus OSM transit stops, NCES school locations and EDFacts district ratings, and airports onto a geohash6 grid (64,320 cells). A manual job builds the road-bounded areas.
2. **Scoring** normalizes each factor within its metro area and combines them with weights; `null` is never 0.
3. **Serving:** FastAPI on AWS Lambda behind API Gateway reads scores from Postgres (Supabase, with pgvector); the Next.js site runs on AWS Amplify. All infrastructure is Terraform; deploys use GitHub Actions with OIDC.

| Area | Stack |
|---|---|
| Frontend | Next.js 15, React 19, TypeScript, MapLibre GL |
| API | Python 3.12, FastAPI, Mangum, OpenAPI contract in `contracts/` |
| Data | Postgres (Supabase), psycopg 3, pgvector |
| AI | Anthropic Haiku 4.5 via `common/llm.py` |
| Infra | Terraform, AWS Lambda / API Gateway / Amplify / SSM / ACM, Cloudflare DNS |
| CI/CD | GitHub Actions (tests, Terraform checks, OIDC deploy, weekly ingestion) |

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): system design, ingestion pipeline, data model and migrations, API endpoints, AI layer, routing, infrastructure and costs.
- [docs/SCORING.md](docs/SCORING.md): the scoring model, what is shipped (v1/v2/v2.1) and the planned v3 framework.
- [docs/ROADMAP.md](docs/ROADMAP.md): goals, status, improvement plan and decisions log.
- [docs/api.md](docs/api.md): API guide with examples. [docs/data-sources.md](docs/data-sources.md): school data decisions.

## Repo map

| Path | Contents |
|---|---|
| `web/` | Next.js app (pages, components, generated API types, vitest tests) |
| `api/` | FastAPI routes, explanations, chat, optimizer, Lambda handler |
| `scoring/` | Scoring engine (`engine.py`), runner, similarity embeddings |
| `ingestion/` | One module per data source, plus `areas/` (polygon builder) and `neighborhoods.py` |
| `common/` | Shared DB layer, Overpass client, LLM client, geo and unit helpers |
| `contracts/` | `openapi.yaml`, `schema.sql`, numbered `migrations/` |
| `infra/` | Terraform for AWS and Cloudflare DNS |
| `docs/` | Documentation (above) |
| `scripts/`, `tests/` | Build and evaluation scripts; Python tests |

## Running it locally

Requires Python 3.10+, Node 20+, and a Postgres database (`docker compose up db` starts one).

```bash
# Backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"         # ingestion on its own needs ".[schools]" (shapely, pyshp); dev already includes them
cp .env.example .env            # set DATABASE_URL (LOCATIONIQ_API_KEY is optional)
pytest                          # tests need no database
python -m ingestion.grid        # build the grid, then run the other ingestion.* modules
python -m scoring.run           # compute scores (set SCORING_WEIGHTS_VERSION=v2-handtuned for v2)
uvicorn api.main:app --port 8000

# Road-bounded areas for click-to-polygon (manual, not in the weekly workflow)
python -m ingestion.areas.build --source region --write --allow-network

# Optional: vector tiles for the map (Docker; see docs/ARCHITECTURE.md "Vector tiles")
python scripts/build_tiles.py --out build/tiles

# Frontend (in another terminal)
cd web
cp .env.example .env.local      # points at http://localhost:8000/v1
npm install
npm run dev                     # http://localhost:3000
npm run check                   # lint + typecheck + tests + build
```

Optional web build flags (off by default): `NEXT_PUBLIC_PMTILES_URL` draws the cell grid from a PMTiles file, and `NEXT_PUBLIC_CHAT_STREAM_URL` streams chat progress from a Lambda function URL. Both are documented in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

Ingestion queries public OpenStreetMap servers, so a full run takes about 45 minutes and should be used sparingly. The weekly GitHub Actions workflow runs the grid, then the sources one at a time, then scoring. Without a `LOCATIONIQ_API_KEY`, address autocomplete uses Photon only.

## Data and attribution

Map data © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright) (ODbL). Basemap by [OpenFreeMap](https://openfreemap.org) © [OpenMapTiles](https://openmaptiles.org). Address search by [LocationIQ](https://locationiq.com), [Photon](https://photon.komoot.io) and [Nominatim](https://nominatim.org) (OSM). Also [NYC Open Data](https://opendata.cityofnewyork.us), [MTA](https://www.mta.info/developers) (including LIRR and Metro-North), PATH and [NJ Transit](https://www.njtransit.com) open GTFS feeds, plus OpenStreetMap transit stops. School locations from [NCES](https://nces.ed.gov/programs/edge/) (EDGE), district boundaries from Census TIGER/Line, and district ratings from EDFacts proficiency data via the [Education Data Portal](https://educationdata.urban.org/) (Urban Institute, ODC Attribution License). GreatSchools is linked, not ingested. Details in [docs/data-sources.md](docs/data-sources.md).

## License

[MIT](LICENSE)
