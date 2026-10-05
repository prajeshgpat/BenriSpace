"""DB-wiring layer around scoring/engine.py's pure functions. Not unit
tested here (needs a live Postgres) — the logic worth testing without a DB
lives in engine.py and is covered by tests/test_scoring_engine.py.
"""

import sys

import psycopg

from common.config import SCORING_WEIGHTS_VERSION
from common.db import get_connection
from common.feature_columns import from_db_row
from common.ingestion_log import ingestion_job
from scoring.engine import all_score_columns, score_metro_cohort
from scoring.scales import Scales, compute_scales, scales_to_rows

SCALES_UPSERT_SQL = """
    insert into score_scales (weights_version, metro_area, factor, component, lo, hi, n)
    values (%s, %s, %s, %s, %s, %s, %s)
    on conflict (weights_version, metro_area, factor, component) do update
    set lo = excluded.lo, hi = excluded.hi, n = excluded.n, computed_at = now()
"""


def quantize(column: str, value):
    """Storage form of a score (migration 0017): sub-scores are whole points (smallint),
    the composite keeps one decimal (real). None stays None."""
    if value is None:
        return None
    if column == "composite_score":
        return round(float(value), 1)
    return int(float(value) + 0.5)


def write_scales(conn, weights_version: str, metro_area: str, scales: Scales) -> int:
    """Upserts a metro's factor scales (migration 0013). Returns rows written, or 0 when
    the score_scales table does not exist yet (the API then computes them itself)."""
    rows = scales_to_rows(weights_version, metro_area, scales)
    try:
        with conn.cursor() as cur:
            cur.executemany(SCALES_UPSERT_SQL, rows)
        conn.commit()
    except psycopg.errors.UndefinedTable:
        conn.rollback()
        return 0
    return len(rows)


def run() -> None:
    with get_connection() as conn, ingestion_job("scoring") as ctx:
        with conn.cursor() as cur:
            cur.execute("select distinct metro_area from geo_entities")
            metro_areas = [r["metro_area"] for r in cur]

        total_written = 0
        for metro_area in metro_areas:
            with conn.cursor() as cur:
                cur.execute(
                    """
                        select fs.*
                        from feature_store fs
                        join geo_entities ge on ge.id = fs.geo_entity_id
                        where ge.metro_area = %s
                        """,
                    (metro_area,),
                )
                rows = [from_db_row(r) for r in cur]  # imperial columns -> metric keys
                for r in rows:
                    r["geo_entity_id"] = str(r["geo_entity_id"])

            scored = score_metro_cohort(rows, SCORING_WEIGHTS_VERSION)
            if not scored:
                continue

            with conn.cursor() as cur:
                for geo_id, found in scored.items():
                    # Every score column is written, NULL when absent, so a score that
                    # no longer applies (e.g. a school with no rating) clears the old value.
                    values = {
                        c: quantize(c, found.get(c))
                        for c in all_score_columns(SCORING_WEIGHTS_VERSION)
                    }
                    columns = [*values.keys(), "geo_entity_id", "weights_version"]
                    placeholders = ", ".join(["%s"] * len(columns))
                    cur.execute(
                        f"""
                            insert into scores ({", ".join(columns)})
                            values ({placeholders})
                            on conflict (geo_entity_id, weights_version) do update
                            set {", ".join(f"{c} = excluded.{c}" for c in values)},
                                computed_at = now()
                            """,
                        [*values.values(), geo_id, SCORING_WEIGHTS_VERSION],
                    )
            conn.commit()
            total_written += len(scored)

            # Keep the normalization constants so a point that is not a cell can be
            # scored on demand the same way (api/point_score.py).
            n_scales = write_scales(
                conn,
                SCORING_WEIGHTS_VERSION,
                metro_area,
                compute_scales(rows, SCORING_WEIGHTS_VERSION),
            )
            if not n_scales:
                print("score_scales table missing (migration 0013); skipped.", file=sys.stderr)

        ctx.rows_affected = total_written

    print(f"Wrote {total_written} score rows.", file=sys.stderr)


if __name__ == "__main__":
    run()
