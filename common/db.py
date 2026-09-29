"""Thin Postgres access layer over contracts/schema.sql. Every ingestion
script and the API import this rather than opening their own connections,
so there's one place that knows the schema's shape.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from common.config import DATABASE_URL

# feature_store columns an ingestion job is allowed to write. Used to
# validate upsert_feature_store() calls so a typo'd column name fails at
# call time, not as a silent no-op.
FEATURE_STORE_COLUMNS = {
    "grocery_count_500m",
    "grocery_nearest_m",
    "gym_count_500m",
    "gym_nearest_m",
    "cafe_count_500m",
    "cafe_nearest_m",
    "gas_station_count_500m",
    "gas_station_nearest_m",
    "convenience_store_count_500m",
    "convenience_store_nearest_m",
    "transit_stop_count_800m",
    "transit_nearest_m",
    "transit_agencies",
    "school_count_1600m",
    "school_nearest_m",
    "school_avg_rating_1600m",
    "road_classification",
    "congestion_proxy_raw",
    "emergency_corridor_proxy_raw",
    "street_orientation",
    "nearest_tier1_airport_code",
    "airport_drive_time_min",
    "running_trail_count_800m",
    "running_trail_nearest_m",
    "strava_segment_count_800m",
    "strava_segment_popularity_raw",
}


@contextmanager
def get_connection() -> Iterator[psycopg.Connection]:
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    try:
        yield conn
    finally:
        conn.close()


def iter_geo_entities(
    conn: psycopg.Connection, metro_area: str | None = None
) -> Iterator[dict]:
    """Yields {id, geohash, latitude, longitude, metro_area} for every grid
    cell. Ingestion scripts loop over this to know what to query POI/GTFS/
    school/road sources against."""
    sql = "select id, geohash, latitude, longitude, metro_area from geo_entities"
    params: tuple = ()
    if metro_area:
        sql += " where metro_area = %s"
        params = (metro_area,)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        yield from cur


def upsert_feature_store(conn: psycopg.Connection, geo_entity_id: str, fields: dict) -> None:
    """Updates only the given columns for one geo_entity_id, inserting the
    row first if it doesn't exist yet. Unknown column names raise —
    catches typos instead of silently dropping data."""
    unknown = set(fields) - FEATURE_STORE_COLUMNS
    if unknown:
        raise ValueError(f"Unknown feature_store columns: {unknown}")
    if not fields:
        return

    columns = list(fields)
    values = [fields[c] for c in columns]
    set_clause = ", ".join(f"{c} = %s" for c in columns)
    insert_placeholders = ", ".join(["%s"] * (len(columns) + 1))

    sql = f"""
        insert into feature_store (geo_entity_id, {", ".join(columns)})
        values ({insert_placeholders})
        on conflict (geo_entity_id) do update
        set {set_clause}, updated_at = now()
    """
    with conn.cursor() as cur:
        cur.execute(sql, [geo_entity_id, *values, *values])


def log_ingestion_run(
    conn: psycopg.Connection,
    source: str,
    status: str,
    rows_affected: int | None = None,
    error_message: str | None = None,
    run_id: str | None = None,
) -> str:
    """Insert (run_id=None) or update (run_id given) an ingestion_runs row.
    Call once with status='running' at job start, then again with
    status='success'/'failed' at job end, per PROJECT.md's per-source
    ingestion job pattern."""
    with conn.cursor() as cur:
        if run_id is None:
            cur.execute(
                """
                insert into ingestion_runs (source, status, rows_affected, error_message)
                values (%s, %s, %s, %s)
                returning id
                """,
                (source, status, rows_affected, error_message),
            )
            row = cur.fetchone()
            conn.commit()
            return str(row["id"])
        cur.execute(
            """
            update ingestion_runs
            set status = %s, rows_affected = %s, error_message = %s, finished_at = now()
            where id = %s
            """,
            (status, rows_affected, error_message, run_id),
        )
        conn.commit()
        return run_id


# --- Read-oriented additions for api/ (GET /score, /score/{id}/explanation,
# POST /triangulate). Appended, not mixed into the functions above, per
# instructions: other agents' code already depends on get_connection(),
# iter_geo_entities(), upsert_feature_store(), and log_ingestion_run()
# behaving exactly as they do today.


def get_geo_entity_by_geohash(conn: psycopg.Connection, geohash: str) -> dict | None:
    """Exact geohash6 match for GET /score's primary lookup path. Returns
    None on a miss -- callers fall back to get_geo_entities_in_bbox() +
    nearest-by-haversine in Python (see api/lookup.py)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select id, geohash, latitude, longitude, formatted_address, metro_area
            from geo_entities
            where geohash = %s
            """,
            (geohash,),
        )
        return cur.fetchone()


def get_geo_entities_in_bbox(
    conn: psycopg.Connection, min_lat: float, max_lat: float, min_lon: float, max_lon: float
) -> list[dict]:
    """Candidate rows for the GET /score fallback when the exact geohash6
    cell misses. Cheap at this scale (~64k geo_entities metro-wide) --
    nearest-neighbor selection among the bbox result happens in Python via
    common.geo.haversine_m, not in SQL."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select id, geohash, latitude, longitude, formatted_address, metro_area
            from geo_entities
            where latitude between %s and %s and longitude between %s and %s
            """,
            (min_lat, max_lat, min_lon, max_lon),
        )
        return list(cur)


def get_latest_score(conn: psycopg.Connection, geo_entity_id: str) -> dict | None:
    """Most recent (by computed_at) scores row for one geo_entity, whatever
    weights_version that happens to be. Phase 1 doesn't expose a
    weights_version query param yet (per api/ instructions: "for now just
    take the newest row") -- that's a natural later addition here without
    touching callers' shapes."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select *
            from scores
            where geo_entity_id = %s
            order by computed_at desc
            limit 1
            """,
            (geo_entity_id,),
        )
        return cur.fetchone()


def iter_latest_scored_geo_entities(conn: psycopg.Connection) -> Iterator[dict]:
    """Yields one row per geo_entity -- its most-recent-by-computed_at score
    joined with geo_entities identity fields (geo_entity_id, address, lat/
    lon, composite_score, weights_version, computed_at). Used by
    POST /triangulate, which needs the whole metro's current composite
    scores in memory (~64k rows) to test against the Phase 1 isochrone-
    circle placeholder in Python -- see api/triangulate.py."""
    sql = """
        select distinct on (s.geo_entity_id)
            s.geo_entity_id, s.composite_score, s.weights_version, s.computed_at,
            ge.formatted_address, ge.latitude, ge.longitude
        from scores s
        join geo_entities ge on ge.id = s.geo_entity_id
        order by s.geo_entity_id, s.computed_at desc
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        yield from cur
