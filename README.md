# BenriSpace

**Live site: [benrispace.com](https://benrispace.com)** · **API: [api.benrispace.com/docs](https://api.benrispace.com/docs)** · [API guide](docs/api.md)

*Benri* (便利) means "convenient". BenriSpace scores any address in the New York metro area (NYC, Long Island, Westchester, the Hudson Valley, northern New Jersey and Fairfield County, CT) on how convenient daily life is there, and shows where the convenient places are on a map. The idea: your 10-minute radius dictates your life, so see what is around any address.

**Status (October 2026).** Production serves the `v2.2-density` model (live since 2026-10-06): 13 factors scored once per road-bounded area from routed travel times, on one absolute scale for the whole region. Ask Benri (chat) and an MCP connector for Claude are live; Login and Pricing are UI only. See [docs/ROADMAP.md](docs/ROADMAP.md).

## Features (shipped today)

- **Score out of 100** for any address or map click, built from the factors you choose: groceries, restaurants, cafes, bars, gym, shopping, public transit, airport, gas and convenience, traffic, schools, noise corridor and recreation. Scores measure what you can reach on foot (or by a short drive in car-dependent areas) on one scale for NY, NJ and CT. A missing measurement shows "No data", never 0.
- **Neighborhood areas.** Clicking the map outlines the road-bounded area under it (35,943 areas, about 0.1 to 1 sq mi, smaller where it is denser) and names it ("Park Slope, Brooklyn"). It falls back to the grid cell when no area fits.
- **Best areas** ranked for your factors, with numbered map markers (hover or focus one for its name and score), presets (Daily errands, Family, Commuter, Quiet) and importance sliders.
- **AI summary** of a score (Claude Haiku 4.5, grounded in that area's data only, capped at about $5/month, with a rule-based fallback).
- **Improve this area:** which nearby additions would lift weak factors, with named places.
- **Similar areas** found by comparing per-metro z-scored factor profiles (in the browser from the area file, with the API as fallback).
- **Multi-stop planning** (`/v1/optimize`): near work, Trader Joe's and Planet Fitness at once, ranked by weekly travel time (openrouteservice refinement).
- **Travel-time overlap.** Add points of interest (work, a gym, family) to the searched place. Each gets a travel-time area, and the best areas are ranked where they overlap. Every mode starts at 10 minutes. Each travel toggle (the one in the search box for the searched place, and one per point of interest) shows its mode icon with the minutes in a small circle; its chevron opens the modes and a minutes stepper (walk up to 30 minutes, train 45, drive 60). The searched place's panel also has a "Show on map" switch for its pink travel boundary (on by default; a key under the map says what the line means, and over an overlap you can switch it on as an override). The searched place is the one you go to most, so it keeps its own mode and 10 minutes; once per new set of places each point of interest gets only the extra minutes it needs to overlap it (a grocery store far out may get 25 while work stays at 10), moving to a faster mode only past its mode's maximum, and widening the farthest point of interest up to two steps if the overlap is still empty and you have not changed anything. The two point-of-interest boxes stay side by side on any screen width, and the overlap list is numbered like the markers on the map. Pins are moved onto land, so none sits in a river. The map centres on a pin, or fits all pins, when you click a pin, score an address, enter a point of interest or pick an overlap, best or similar area. With an overlap area picked, a stray map tap clears the pick instead of moving the searched place.
- **Address search** with autocomplete (LocationIQ, Photon fallback when no key is set), "use my current location", readable addresses for clicked points, shareable URLs, light and dark themes, and a phone bottom-sheet layout. Distances are in feet and miles.
- **Ask Benri** chat, grounded in BenriSpace's own tools. A request like "find me a place near work close to Planet Fitness and Whole Foods" sets up the searched place, points of interest and their overlap on the map.
- **Compare** 2-4 pinned places side by side.
- **Public API**, no key needed today: [docs/api.md](docs/api.md). **MCP connector** so Claude can use BenriSpace: `https://api.benrispace.com/mcp`.

Pages: Home (`/`, the explainer, linked from the logo) and the header tabs Map (`/app`, search and score panel beside the map), For Business (`/business`), Developers (`/docs`: API and MCP connector sections, linking to Data sources at `/data`) and Pricing (Free $0, Pro $9/mo or $90/yr as a placeholder, Business contact us); plus Settings and Login. Pricing and Login are UI only: auth and payments are not wired yet.

Known limits: scores are per road-bounded area, so every point in an area shares its score; school ratings are district-level; travel times are free-flow (no live traffic) and train times use weekday morning-peak schedules; buses count toward transit but are not routed.

## How it works

Scores are precomputed in batch, so the API is a thin read layer.

1. **Ingestion** (weekly, GitHub Actions) pulls OpenStreetMap (Overpass), GTFS feeds (MTA, LIRR, Metro-North, PATH, NJ Transit) plus OSM transit stops, NCES school locations and EDFacts district ratings, airports and Census population density onto a geohash6 grid (64,320 cells).
2. **Routing and scoring** (monthly, local): walk and drive networks from Geofabrik extracts give routed minutes between cells, to the nearest places and to train stations and airports. `scoring.area_run` scores each road-bounded area from those routed times and place densities on one absolute scale; `null` is never 0.
3. **Serving:** FastAPI on AWS Lambda behind API Gateway reads precomputed data from Postgres (Supabase, with PostGIS); the Next.js site runs on AWS Amplify and scores the map in the browser from a compact score file on Cloudflare R2. All infrastructure is Terraform; deploys use GitHub Actions with OIDC.

| Area | Stack |
|---|---|
| Frontend | Next.js 15, React 19, TypeScript, MapLibre GL |
| API | Python 3.12, FastAPI, Mangum, OpenAPI contract in `contracts/` |
| Data | Postgres (Supabase), psycopg 3, PostGIS; Cloudflare R2 for static files and PMTiles |
| AI | Anthropic Haiku 4.5 via `common/llm.py` |
| Routing | Pandana (contraction hierarchies) over Geofabrik OSM extracts, GTFS Connection Scan for trains |
| Infra | Terraform, AWS Lambda / API Gateway / Amplify / SSM / ACM / CloudWatch, Cloudflare DNS and R2 |
| CI/CD | GitHub Actions (tests, Playwright E2E, Terraform checks, OIDC deploy, weekly ingestion) |

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): system design, ingestion pipeline, data model and migrations, API endpoints, AI layer, routing, infrastructure and costs.
- [docs/SCORING.md](docs/SCORING.md): the scoring model, what is shipped (v2.1, v2.2) and the planned v3 framework.
- [docs/ROADMAP.md](docs/ROADMAP.md): goals, status, improvement plan and decisions log. [docs/PLANNED.md](docs/PLANNED.md): the backlog.
- [docs/api.md](docs/api.md): API guide with examples. [docs/data-sources.md](docs/data-sources.md): data sources, licences and decisions.

## Repo map

| Path | Contents |
|---|---|
| `web/` | Next.js app (pages, components, generated API types, vitest tests) |
| `api/` | FastAPI routes, explanations, chat, optimizer, Lambda handler |
| `scoring/` | Scoring engine (`engine.py`), cell runner, per-area density scoring (`area_run.py`, `density.py`), scales, point scoring, similarity helpers |
| `ingestion/` | One module per data source, plus `areas/` (polygon builder), `routing/` (networks, routed tables, area reach) and `neighborhoods.py` |
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
python -m scoring.run           # cell scores for v2.1-handtuned (the weekly job's step)
uvicorn api.main:app --port 8000

# Road-bounded areas for click-to-polygon (manual, not in the weekly workflow)
python -m ingestion.areas.build --source region --write --allow-network

# v2.2 density scores (needs the `routing` extra, Geofabrik extracts in build/osm; see docs/ARCHITECTURE.md section 2)
python -m ingestion.routing.pbf && python -m ingestion.routing.reach && python -m scoring.area_run

# Optional: vector tiles for the map (Docker; see docs/ARCHITECTURE.md "Vector tiles")
python scripts/build_tiles.py --out build/tiles

# Frontend (in another terminal)
cd web
cp .env.example .env.local      # points at http://localhost:8000/v1
npm install
npm run dev                     # http://localhost:3000
npm run check                   # lint + typecheck + tests + build
```

Optional web build flags: `NEXT_PUBLIC_STATIC_URL` reads the score file, area file and tiles from R2 (set in production), `NEXT_PUBLIC_SCORE_PRECISION=point` scores the exact clicked point (set in production), `NEXT_PUBLIC_PMTILES_URL` overrides the tiles, and `NEXT_PUBLIC_CHAT_STREAM_URL` streams chat progress from a Lambda function URL (off). Both are documented in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

Ingestion queries public OpenStreetMap servers, so a full run takes about 45 minutes and should be used sparingly. The weekly GitHub Actions workflow runs the grid, then the sources one at a time, then scoring and the score file publish. Without a `LOCATIONIQ_API_KEY`, address autocomplete uses Photon only.

## Data and attribution

Map data © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright) (ODbL). Basemap by [OpenFreeMap](https://openfreemap.org) © [OpenMapTiles](https://openmaptiles.org). Address search by [LocationIQ](https://locationiq.com), [Photon](https://photon.komoot.io) and [Nominatim](https://nominatim.org) (OSM). Also [NYC Open Data](https://opendata.cityofnewyork.us), [MTA](https://www.mta.info/developers) (including LIRR and Metro-North), PATH and [NJ Transit](https://www.njtransit.com) open GTFS feeds, plus OpenStreetMap transit stops. School locations from [NCES](https://nces.ed.gov/programs/edge/) (EDGE), district boundaries from Census TIGER/Line, and district ratings from EDFacts proficiency data via the [Education Data Portal](https://educationdata.urban.org/) (Urban Institute, ODC Attribution License). GreatSchools is linked, not ingested. Details in [docs/data-sources.md](docs/data-sources.md).

## License

[MIT](LICENSE)
