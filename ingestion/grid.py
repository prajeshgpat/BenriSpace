"""Populates geo_entities with a geohash grid over the v1 metro area.

This is foundational, not an ingestion job like the others: every POI/GTFS/
school/road/airport ingestion script writes into feature_store keyed by
geo_entity_id, so those rows have to exist first and have to come from one
shared grid — if each ingestion script invented its own cells independently
(e.g. "wherever a POI happens to be"), they wouldn't line up into a common
address/geohash index at all.

Design calls made here (flag if wrong, easy to change):

- **Precision: geohash6** (~1.22km x 0.61km per cell). Coarser precisions
  (5) are too coarse to distinguish neighborhoods; finer (7, ~153m) would
  push row counts for a 1-2hr-radius NYC metro into the hundreds of
  thousands-plus, working against the $0/month target for no clear benefit
  at MVP stage.
- **Bounding boxes are approximate rectangles**, not precise shapefiles —
  land/water isn't filtered, so some ocean/reservoir cells get created.
  They'll just never accumulate POIs and will score near-empty; not a
  correctness bug, just some wasted (cheap) rows. Precise polygon boundaries
  are a fine later improvement, not needed to unblock ingestion.
- **metro_area labels** match the sub-regions named in PROJECT.md's v1
  scope, and matter beyond bookkeeping: normalization (contracts/
  normalization.md) min-max normalizes within metro_area specifically so
  suburban/exurban areas aren't flattened against urban density.
"""

import sys

import pygeohash as pgh

from common.db import get_connection
from common.ingestion_log import ingestion_job

GEOHASH_PRECISION = 6
LAT_STEP = 0.0054  # ~geohash6 cell height in degrees
LON_STEP = 0.0110  # ~geohash6 cell width in degrees at mid-latitudes

# (metro_area, min_lat, max_lat, min_lon, max_lon)
BOUNDING_BOXES = [
    ("nyc", 40.49, 40.92, -74.26, -73.70),
    ("long_island", 40.55, 41.20, -73.75, -71.85),
    ("westchester", 40.87, 41.40, -73.95, -73.60),
    ("hudson_valley", 41.10, 42.00, -74.50, -73.60),
    ("northern_nj", 39.85, 41.10, -75.20, -73.90),
    ("fairfield_ct", 40.95, 41.40, -73.75, -73.05),
]


def generate_cells() -> dict[str, tuple[str, float, float]]:
    """Returns {geohash: (metro_area, lat, lon)}, deduped so overlapping
    boxes (e.g. nyc/westchester border) don't collide — first box in
    BOUNDING_BOXES order wins a shared cell."""
    cells: dict[str, tuple[str, float, float]] = {}
    for metro_area, min_lat, max_lat, min_lon, max_lon in BOUNDING_BOXES:
        lat = min_lat
        while lat <= max_lat:
            lon = min_lon
            while lon <= max_lon:
                geohash = pgh.encode(lat, lon, precision=GEOHASH_PRECISION)
                if geohash not in cells:
                    cells[geohash] = (metro_area, lat, lon)
                lon += LON_STEP
            lat += LAT_STEP
    return cells


def run() -> None:
    cells = generate_cells()
    rows = [
        (geohash, lat, lon, metro_area)
        for geohash, (metro_area, lat, lon) in cells.items()
    ]

    with get_connection() as conn, ingestion_job(conn, "grid_generation") as ctx:
        with conn.cursor() as cur:
            cur.executemany(
                """
                    insert into geo_entities (geohash, latitude, longitude, metro_area)
                    values (%s, %s, %s, %s)
                    on conflict (geohash) do nothing
                    """,
                rows,
            )
        conn.commit()
        ctx.rows_affected = len(rows)

    print(f"Generated/confirmed {len(rows)} geo_entities cells.", file=sys.stderr)


if __name__ == "__main__":
    run()
