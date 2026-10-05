"""Data transparency: the sources behind the scores (GET /v1/sources).

SOURCES is the static registry (what each source feeds, its licence and link).
`freshness()` joins it with the latest successful ingestion_runs row per job.
"""

from dataclasses import dataclass

import psycopg


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    feeds: str
    license: str
    url: str
    jobs: tuple[str, ...]  # ingestion_runs.source values that refresh it


OSM_LICENSE = "ODbL 1.0 (c) OpenStreetMap contributors"

SOURCES: tuple[Source, ...] = (
    Source("osm_poi", "OpenStreetMap points of interest",
           "Grocery, gym, cafe, restaurant, bar, shopping, gas and convenience, recreation factors; place names",
           OSM_LICENSE, "https://www.openstreetmap.org/copyright", ("osm_poi", "osm_retail_parks")),
    Source("osm_roads", "OpenStreetMap roads and rail",
           "Traffic and Noise factors", OSM_LICENSE,
           "https://www.openstreetmap.org/copyright", ("osm_roads",)),
    Source("osm_transit", "OpenStreetMap transit stops",
           "Transit factor (stops outside GTFS feeds)", OSM_LICENSE,
           "https://www.openstreetmap.org/copyright", ("osm_transit",)),
    Source("trails", "OpenStreetMap trails and parks",
           "Recreation factor", OSM_LICENSE, "https://www.openstreetmap.org/copyright", ("trails",)),
    Source("gtfs", "Transit schedules (MTA, LIRR, Metro-North, NJ Transit, PATH)",
           "Transit factor", "Agency open-data terms (free to use with attribution)",
           "https://www.mta.info/developers",
           ("gtfs_mta", "gtfs_lirr", "gtfs_metro_north", "gtfs_nj_transit", "gtfs_path", "gtfs_transit")),
    Source("schools", "NCES school locations and state school-district boundaries",
           "School factor", "Public domain (US federal data)",
           "https://nces.ed.gov/programs/edge/", ("schools",)),
    Source("airports", "OurAirports and FAA airport data",
           "Airport access factor", "Public domain (OurAirports) / US government data",
           "https://ourairports.com/data/", ("airports",)),
    Source("neighborhoods", "OpenStreetMap neighborhood names",
           "Neighborhood labels", OSM_LICENSE, "https://www.openstreetmap.org/copyright",
           ("neighborhoods",)),
    Source("grid", "BenriSpace grid, areas and scoring",
           "The 0.8 sq mi cells, road-bounded areas and 13 scores",
           "BenriSpace derived data", "https://benrispace.com",
           ("grid_generation", "scoring")),
)


def freshness(conn) -> dict[str, dict]:
    """{ingestion job: {finishedAt, rowsAffected}} for each job's latest success.
    Empty when ingestion_runs cannot be read."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select distinct on (source) source, finished_at, rows_affected "
                "from ingestion_runs where status = 'success' and finished_at is not null "
                "order by source, finished_at desc"
            )
            return {
                r["source"]: {"finishedAt": r["finished_at"], "rowsAffected": r["rows_affected"]}
                for r in cur
            }
    except psycopg.Error:
        conn.rollback()
        return {}


def build_sources(runs: dict[str, dict]) -> list[dict]:
    """Registry entries with `lastUpdated` (latest finished job) and `rowsAffected`
    (summed over the jobs that refresh the source); null when never run."""
    out = []
    for s in SOURCES:
        done = [runs[j] for j in s.jobs if j in runs]
        last = max((d["finishedAt"] for d in done), default=None)
        rows = [d["rowsAffected"] for d in done if d["rowsAffected"] is not None]
        out.append(
            {
                "id": s.id,
                "name": s.name,
                "feeds": s.feeds,
                "license": s.license,
                "url": s.url,
                "lastUpdated": last,
                "rowsAffected": sum(rows) if rows else None,
            }
        )
    return out
