"""Thin Postgres access layer over contracts/schema.sql. Every ingestion
script and the API import this rather than opening their own connections,
so there's one place that knows the schema's shape.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from common.config import DATABASE_URL
from scoring.engine import CATEGORY_SPECS

# feature_store columns typed `jsonb` in schema.sql -- values for these
# must be wrapped with Jsonb() before binding, or psycopg's default list/
# dict adapter produces Postgres array/composite literal syntax instead of
# JSON (hit live 2026-09-29: a Python list for transit_agencies came out
# as `{mta}`, which Postgres's jsonb parser correctly rejected as invalid
# JSON -- `{` starts an object, not an array).
FEATURE_STORE_JSON_COLUMNS = {"transit_agencies"}

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
    """Every ingestion script loops over ~64k geo_entities doing one
    upsert_feature_store() call per row -- against a remote DB (Supabase's
    pooler, not localhost) that's ~64k synchronous round-trips if each
    statement waits for its own acknowledgment, discovered when the first
    live run against real Supabase took over 3 minutes without writing a
    single row. Pipeline mode batches those round-trips transparently --
    every caller (iter_geo_entities' one read, upsert_feature_store's many
    writes) keeps working exactly as written, psycopg just stops waiting
    for each statement's ack before sending the next one."""
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    try:
        with conn.pipeline():
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
    values = [
        Jsonb(fields[c]) if c in FEATURE_STORE_JSON_COLUMNS and fields[c] is not None else fields[c]
        for c in columns
    ]
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
    source: str,
    status: str,
    rows_affected: int | None = None,
    error_message: str | None = None,
    run_id: str | None = None,
) -> str:
    """Insert (run_id=None) or update (run_id given) an ingestion_runs row.
    Call once with status='running' at job start, then again with
    status='success'/'failed' at job end, per PROJECT.md's per-source
    ingestion job pattern.

    Deliberately opens its own short-lived, non-pipelined connection
    rather than taking one as a parameter: this is the one write that must
    always land reliably, including especially when something on the
    caller's main (pipelined) connection just failed. Discovered live
    2026-09-29 that pipeline mode defers errors to the next sync point
    (not the failing execute() call itself) and leaves the pipeline in an
    aborted state until then -- a failure-logging call sharing that
    connection could itself fail (PipelineAborted) or silently never run,
    masking the real error and leaving the row stuck at 'running' forever.
    A handful of calls per job run (start/success/failure) is cheap enough
    that a fresh connection each time isn't worth optimizing away."""
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    try:
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
    finally:
        conn.close()


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


# --- Map queries (GET /map/cells, GET /map/top). The composite is a weighted
# average of the STORED sub-scores, computed in SQL so a viewport of tens of
# thousands of cells never crosses the wire as raw rows. Semantics match
# scoring.engine.compute_composite: only non-null sub-scores contribute, to
# both numerator and denominator; a row with every selected factor null has
# no composite (NULL) and is dropped.

MAP_SCORE_COLUMNS = frozenset(spec.score_column for spec in CATEGORY_SPECS)

# (min_lon, min_lat, max_lon, max_lat)
MapBbox = tuple[float, float, float, float]

_BBOX_WHERE = "and ge.latitude between %s and %s and ge.longitude between %s and %s"


def build_composite_sql(columns_weights: list[tuple[str, float]]) -> tuple[str, list[float]]:
    """SQL expression (alias `s` = scores) and its bound params, in text order.
    Column names come only from the scoring.engine whitelist; weights are
    bound parameters."""
    if not columns_weights:
        raise ValueError("at least one factor is required")
    unknown = {col for col, _ in columns_weights} - MAP_SCORE_COLUMNS
    if unknown:
        raise ValueError(f"not a scores column: {sorted(unknown)}")
    numerator = " + ".join(f"coalesce(s.{col}, 0) * %s::float8" for col, _ in columns_weights)
    denominator = " + ".join(
        f"(case when s.{col} is null then 0 else %s::float8 end)" for col, _ in columns_weights
    )
    weights = [float(w) for _, w in columns_weights]
    return f"(({numerator}) / nullif({denominator}, 0))", weights + weights


def _bbox_params(bbox: MapBbox | None) -> list[float]:
    if bbox is None:
        return []
    min_lon, min_lat, max_lon, max_lat = bbox
    return [min_lat, max_lat, min_lon, max_lon]


def build_map_cells_sql(
    columns_weights: list[tuple[str, float]],
    weights_version: str,
    bbox: MapBbox,
    precision: int,
    limit: int,
) -> tuple[str, list]:
    expr, expr_params = build_composite_sql(columns_weights)
    params: list = [*expr_params, weights_version, *_bbox_params(bbox)]
    if precision == 6:
        sql = f"""
            select geohash, score from (
                select ge.geohash as geohash, {expr} as score
                from scores s join geo_entities ge on ge.id = s.geo_entity_id
                where s.weights_version = %s {_BBOX_WHERE}
            ) t
            where score is not null
            order by geohash
            limit %s
        """
    elif precision == 5:
        sql = f"""
            select g5 as geohash, avg(score) as score from (
                select left(ge.geohash, 5) as g5, {expr} as score
                from scores s join geo_entities ge on ge.id = s.geo_entity_id
                where s.weights_version = %s {_BBOX_WHERE}
            ) t
            where score is not null
            group by g5
            order by g5
            limit %s
        """
    else:
        raise ValueError("precision must be 5 or 6")
    params.append(limit)
    return sql, params


def build_map_top_sql(
    columns_weights: list[tuple[str, float]],
    weights_version: str,
    bbox: MapBbox | None,
    pool: int,
) -> tuple[str, list]:
    expr, expr_params = build_composite_sql(columns_weights)
    sub_score_columns = ", ".join(f"s.{spec.score_column}" for spec in CATEGORY_SPECS)
    bbox_sql = _BBOX_WHERE if bbox is not None else ""
    sql = f"""
        select * from (
            select ge.geohash, ge.latitude, ge.longitude, ge.metro_area,
                   {sub_score_columns}, {expr} as score
            from scores s join geo_entities ge on ge.id = s.geo_entity_id
            where s.weights_version = %s {bbox_sql}
        ) t
        where score is not null
        order by score desc, geohash
        limit %s
    """
    return sql, [*expr_params, weights_version, *_bbox_params(bbox), pool]


def get_map_cells(
    conn: psycopg.Connection,
    columns_weights: list[tuple[str, float]],
    weights_version: str,
    bbox: MapBbox,
    precision: int,
    limit: int,
) -> list[dict]:
    """Up to `limit` rows of {geohash, score}, ordered by geohash."""
    sql, params = build_map_cells_sql(columns_weights, weights_version, bbox, precision, limit)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur)


def get_map_top_candidates(
    conn: psycopg.Connection,
    columns_weights: list[tuple[str, float]],
    weights_version: str,
    bbox: MapBbox | None,
    pool: int,
) -> list[dict]:
    """The `pool` highest-composite cells (with identity and all sub-score
    columns), best first."""
    sql, params = build_map_top_sql(columns_weights, weights_version, bbox, pool)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur)
