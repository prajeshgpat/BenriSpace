"""Similar-areas embeddings: one 14-dim vector per scored cell.

Each dimension is one sub-score, z-scored across the metro so every factor
counts equally regardless of its spread. A NULL sub-score (e.g. school with no
district rating) is imputed with 0.0, which is the mean after z-scoring.
Pure functions up top; run() is the DB wiring (needs Postgres + migration 0007).

    python -m scoring.embeddings
"""

import math
import sys

# The one ordered list of dimensions. The API (api/similar.py) reads the same
# list, so index i of a stored embedding always means EMBEDDING_COLUMNS[i].
EMBEDDING_COLUMNS: tuple[str, ...] = (
    "grocery_score",
    "gym_score",
    "cafe_score",
    "restaurant_score",
    "bar_score",
    "premium_retail_score",
    "gas_station_score",
    "convenience_store_score",
    "transit_score",
    "school_score",
    "road_score",
    "emergency_corridor_score",
    "airport_score",
    "trail_popularity_score",
)
EMBEDDING_DIM = len(EMBEDDING_COLUMNS)
BATCH_SIZE = 1000


def column_stats(rows: list[dict], column: str) -> tuple[float, float]:
    """(mean, population std) over the non-null values; (0.0, 0.0) when none."""
    values = [float(r[column]) for r in rows if r.get(column) is not None]
    if not values:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    return mean, math.sqrt(var)


def zscore(value: float | None, mean: float, std: float) -> float:
    """z-score, 0.0 for a missing value or a zero-variance column."""
    if value is None or std <= 0:
        return 0.0
    return (float(value) - mean) / std


def build_embeddings(rows: list[dict]) -> dict[str, list[float]]:
    """{geo_entity_id: vector} for rows holding the sub-score columns, ordered
    as EMBEDDING_COLUMNS."""
    stats = [column_stats(rows, c) for c in EMBEDDING_COLUMNS]
    return {
        str(r["geo_entity_id"]): [
            zscore(r.get(c), mean, std)
            for c, (mean, std) in zip(EMBEDDING_COLUMNS, stats, strict=True)
        ]
        for r in rows
    }


def vector_literal(vector: list[float]) -> str:
    """pgvector text form, '[a,b,...]' (cast with ::vector)."""
    return "[" + ",".join(f"{v:.6f}" for v in vector) + "]"


def run() -> None:
    from common.config import SCORING_WEIGHTS_VERSION
    from common.db import get_connection
    from common.ingestion_log import ingestion_job

    cols = ", ".join(f"s.{c}" for c in EMBEDDING_COLUMNS)
    with get_connection() as conn, ingestion_job("embeddings") as ctx:
        with conn.cursor() as cur:
            cur.execute("select distinct metro_area from geo_entities")
            metro_areas = [r["metro_area"] for r in cur]

        total = 0
        for metro_area in metro_areas:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    select s.geo_entity_id, {cols}
                    from scores s
                    join geo_entities ge on ge.id = s.geo_entity_id
                    where ge.metro_area = %s and s.weights_version = %s
                    """,
                    (metro_area, SCORING_WEIGHTS_VERSION),
                )
                rows = [dict(r) for r in cur]
            items = list(build_embeddings(rows).items())
            for start in range(0, len(items), BATCH_SIZE):
                batch = items[start : start + BATCH_SIZE]
                with conn.cursor() as cur:
                    cur.executemany(
                        "update scores set embedding = %s::vector "
                        "where geo_entity_id = %s and weights_version = %s",
                        [(vector_literal(v), gid, SCORING_WEIGHTS_VERSION) for gid, v in batch],
                    )
                conn.commit()
            total += len(items)
        ctx.rows_affected = total

    print(f"Wrote {total} embeddings.", file=sys.stderr)


if __name__ == "__main__":
    run()
