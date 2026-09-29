"""DB-wiring layer around scoring/engine.py's pure functions. Not unit
tested here (needs a live Postgres) — the logic worth testing without a DB
lives in engine.py and is covered by tests/test_scoring_engine.py.
"""

import sys

from common.config import SCORING_WEIGHTS_VERSION
from common.db import get_connection
from common.ingestion_log import ingestion_job
from scoring.engine import score_metro_cohort


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
                rows = [dict(r) for r in cur]
                for r in rows:
                    r["geo_entity_id"] = str(r["geo_entity_id"])

            scored = score_metro_cohort(rows)
            if not scored:
                continue

            with conn.cursor() as cur:
                for geo_id, values in scored.items():
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

        ctx.rows_affected = total_written

    print(f"Wrote {total_written} score rows.", file=sys.stderr)


if __name__ == "__main__":
    run()
