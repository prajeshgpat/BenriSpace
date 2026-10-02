# BenriSpace

**Live site: [benrispace.com](https://benrispace.com)** · **API: [api.benrispace.com/docs](https://api.benrispace.com/docs)** · [API guide](docs/api.md)

*Benri* (便利) means "convenient". BenriSpace scores any address in the New York metro area on how convenient daily life is there, and shows where the convenient places are on a map.

Each location gets a 0–100 score built from 11 factors: grocery, gym, cafe, gas station, convenience store, transit, school, road access, emergency corridor, airport, and trail popularity.

## Using the website

- **Score an address** at [benrispace.com](https://benrispace.com). Type an address and pick a suggestion (or press Enter). You get the overall score, each factor's sub-score, and a plain-language explanation.
- **Explore the map** at [benrispace.com/map](https://benrispace.com/map). Cells are coloured by score. Toggle factors on and off, or pick a preset (Daily errands, Family, Commuter, Quiet). The **Best areas** list ranks the strongest spots for the factors you chose.
- **No area scores 100 on everything.** Scores are relative within each metro area, so pick one or two factors to see where each is at its maximum.

Coverage: NYC, Long Island, Westchester, the Hudson Valley, northern New Jersey and Fairfield County, CT.

## Using the API

No key is needed today. Interactive docs are at [api.benrispace.com/docs](https://api.benrispace.com/docs), and [docs/api.md](docs/api.md) has a full guide with examples.

```bash
curl "https://api.benrispace.com/v1/score?address=Grand+Central+Terminal,+New+York"
```

## How it works

Scores are precomputed in batch, so the API is a thin read layer.

1. **Ingestion** pulls OpenStreetMap (via Overpass), GTFS transit feeds, NYC Open Data schools and airports, onto a ~1 km geohash grid (64,320 cells).
2. **Scoring** normalizes each factor within its metro area and combines them with weighted averages. A missing measurement is `null`, never 0.
3. **Serving**: FastAPI on AWS Lambda behind API Gateway reads the scores from Postgres. The Next.js site runs on AWS Amplify.

Everything is defined as code with Terraform, and deploys run through GitHub Actions using OIDC (no stored AWS keys). See [ARCHITECTURE.md](ARCHITECTURE.md) for diagrams and design decisions, and [PHASES.md](PHASES.md) for the roadmap.

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
pip install -e ".[dev]"
cp .env.example .env            # set DATABASE_URL
pytest                          # tests need no database
python -m ingestion.grid        # build the grid, then run the other ingestion.* modules
python -m scoring.run           # compute scores
uvicorn api.main:app --port 8000

# Frontend (in another terminal)
cd web
cp .env.example .env.local      # points at http://localhost:8000/v1
npm install
npm run dev                     # http://localhost:3000
npm run check                   # lint + typecheck + tests + build
```

Ingestion queries public OpenStreetMap servers, so a full run takes about 45 minutes and should be used sparingly.

## Data and attribution

Map data © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright) (ODbL). Basemap by [OpenFreeMap](https://openfreemap.org) / OpenMapTiles. Address search by [Photon](https://photon.komoot.io) and Nominatim. Also NYC Open Data and MTA / LIRR / Metro-North GTFS feeds.

## License

[MIT](LICENSE)
