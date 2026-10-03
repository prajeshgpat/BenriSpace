# BenriSpace

**Live site: [benrispace.com](https://benrispace.com)** · **API: [api.benrispace.com/docs](https://api.benrispace.com/docs)** · [API guide](docs/api.md)

*Benri* (便利) means "convenient". BenriSpace scores any address in the New York metro area on how convenient daily life is there, and shows where the convenient places are on a map.

Each location gets a 0–100 score built from 14 factors: grocery, gym, cafe, restaurant, bar, gas station, convenience store, transit, school, road access, noise corridor, airport, and two underlying signals, premium retail and running route popularity. The website lets you toggle the 12 others; the two underlying signals always count toward the overall score. "Noise corridor" (API key `emergencyCorridor`) means main roads near fire stations, hospitals and police stations, where sirens and through-traffic noise are most likely (a rough proxy, weight 0.75). Running route popularity is built from mapped running trails in OpenStreetMap; Strava segment popularity is an optional enrichment that is not configured today.

**Status (October 2026).** The v2 cutover is done (2026-10-03): 14 factors, click-to-polygon areas, readable addresses, miles everywhere, and the Home and App pages are live, and the API serves 64,320 `v2-handtuned` score rows. School ratings are `null` ("No data") where a district has no rating. Coverage is the New York metro only; nationwide expansion is not planned.

## Using the website

- **Home (`/`).** A static explainer: what the app does, how a score is built, each factor with its weight and caveats, how to read the map, and the data sources.
- **The app (`/app`).** One split-screen page: search and the score panel on the left, the map on the right (stacked under a search bar on phones). Shared links live here, e.g. `/app?address=...`; old links with those parameters on `/` and `/map` redirect to `/app`.
- **Navigation.** Tabs Home, App, API (`/docs`) and Pricing on the left; a lightbulb (light/dark theme, with a recoloured dark map), a gear (Settings, which also holds the theme) and Login on the right. Pricing and Login are placeholders.
- **Score an address.** Type an address and pick a suggestion (LocationIQ autocomplete, Photon as the fallback), press Enter, or use the "use my current location" icon inside the search box. The map flies there and the panel shows the overall score, each factor's sub-score, and a plain-language explanation.
- **Click the map.** Clicking a point outlines the area bounded by secondary-and-larger roads (closed at the coast) that contains it, scores that area, and shows a readable street address for the spot. If no area fits, it falls back to the grid cell. Clicking a Best-areas entry scores that spot too.
- **Explore the map.** Cells are coloured by score. Toggle the 12 user-facing factors on and off (premium retail and running route popularity are underlying and not toggleable), pick a preset (Daily errands, Family, Commuter, Quiet), or set how much each factor matters. The **Best areas** list ranks the strongest, well-separated spots in the current map view for the factors you chose. Distances are in feet and miles throughout.
- **No area scores 100 on everything.** Scores are relative within each metro area, so pick one or two factors to see where each is at its maximum.
- **Know the limits.** Area scores average the underlying ~0.6 x 0.4 mile grid cells, so small neighbouring areas can look alike; some areas are slivers and water is not clipped; school ratings are district-level only; airport time is straight-line until a routing engine exists.

Coverage: NYC, Long Island, Westchester, the Hudson Valley, northern New Jersey and Fairfield County, CT.

## Using the API

No key is needed today. Interactive docs are at [api.benrispace.com/docs](https://api.benrispace.com/docs), and [docs/api.md](docs/api.md) has a full guide with examples for `/score`, `/area`, `/suggest`, `/reverse`, `/map/cells`, `/map/top`, `/triangulate` and score explanations.

```bash
curl "https://api.benrispace.com/v1/score?address=Grand+Central+Terminal,+New+York"
```

## How it works

Scores are precomputed in batch, so the API is a thin read layer.

1. **Ingestion** pulls OpenStreetMap (via Overpass), GTFS transit feeds, NCES school locations and district boundaries, EDFacts district ratings and airports, onto a geohash6 grid of about 0.6 x 0.4 mile cells (64,320 cells). A separate manual job builds road-bounded area polygons (16,277 areas) and maps each to the cells it overlaps.
2. **Scoring** (`v2-handtuned`, weights in `scoring/engine.py`) normalizes each factor within its metro area and combines them with weighted averages. A missing measurement is `null`, never 0; the school score is 20% proximity and 80% rating, and `null` where no rating exists.
3. **Serving**: FastAPI on AWS Lambda behind API Gateway reads the scores from Postgres; an area's score is the area-weighted average of its cells' scores. The Next.js site runs on AWS Amplify.

Everything is defined as code with Terraform, and deploys run through GitHub Actions using OIDC (no stored AWS keys). See [ARCHITECTURE.md](ARCHITECTURE.md) for diagrams and design decisions, [docs/data-sources.md](docs/data-sources.md) for the school data decisions, [contracts/normalization.md](contracts/normalization.md) for the scoring method, and [PHASES.md](PHASES.md) for the roadmap.

| Area | Stack |
|---|---|
| Frontend | Next.js 15, React 19, TypeScript, MapLibre GL |
| API | Python 3.12, FastAPI, Mangum, OpenAPI contract in `contracts/` |
| Data | Postgres (Supabase), psycopg 3, pgvector |
| Infra | Terraform, AWS Lambda / API Gateway / Amplify / SSM / ACM, Cloudflare DNS |
| CI/CD | GitHub Actions (tests, Terraform plan, OIDC deploy, weekly ingestion) |

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

# Frontend (in another terminal)
cd web
cp .env.example .env.local      # points at http://localhost:8000/v1
npm install
npm run dev                     # http://localhost:3000
npm run check                   # lint + typecheck + tests + build
```

Ingestion queries public OpenStreetMap servers, so a full run takes about 45 minutes and should be used sparingly. The weekly GitHub Actions workflow runs the grid, then the sources one at a time, then scoring. Without a `LOCATIONIQ_API_KEY`, address autocomplete uses Photon only.

## Data and attribution

Map data © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright) (ODbL). Basemap by [OpenFreeMap](https://openfreemap.org) © [OpenMapTiles](https://openmaptiles.org). Address search by [LocationIQ](https://locationiq.com), [Photon](https://photon.komoot.io) and [Nominatim](https://nominatim.org) (OSM). Also [NYC Open Data](https://opendata.cityofnewyork.us), [MTA](https://www.mta.info/developers) (including LIRR and Metro-North) and [NJ Transit](https://developer.njtransit.com) GTFS (the NJ Transit key has not been obtained yet, so that feed is not ingested). School locations from [NCES](https://nces.ed.gov/programs/edge/) (EDGE), district boundaries from Census TIGER/Line, and district ratings from EDFacts proficiency data via the [Education Data Portal](https://educationdata.urban.org/) (Urban Institute, ODC Attribution License). GreatSchools is linked, not ingested. Details in [docs/data-sources.md](docs/data-sources.md).

## License

[MIT](LICENSE)
