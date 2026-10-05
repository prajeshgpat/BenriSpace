"""Similar-areas embeddings: one 14-dim vector per scored cell.

Each dimension is one sub-score, z-scored across the metro so every factor
counts equally regardless of its spread. A NULL sub-score (e.g. school with no
district rating) is imputed with 0.0, which is the mean after z-scoring.
Pure functions up top; run() is the DB wiring (needs Postgres + migration 0007).

    python -m scoring.embeddings
"""

import math
import os
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
NEIGHBOURS_PER_CELL = 20
# Rows of the pairwise-distance block held at once: 500 x 64k float32 = 128 MB.
NEIGHBOUR_BLOCK = 500


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


def top_neighbours(
    ids: list[str], vectors: list[list[float]], k: int = NEIGHBOURS_PER_CELL
) -> dict[str, list[tuple[str, float]]]:
    """{id: [(neighbour id, L2 distance), ...]} nearest first, excluding the cell
    itself. Exact brute force with numpy in row blocks (64k cells x 14 dims takes
    well under a minute and needs no index); ties break by position. Needs numpy,
    which is part of the ingestion extras (.[geo], .[dev]) but not the Lambda
    bundle."""
    import numpy as np

    n = len(ids)
    if n < 2:
        return {i: [] for i in ids}
    k = min(k, n - 1)
    x = np.asarray(vectors, dtype=np.float32)
    sq = (x * x).sum(axis=1)
    out: dict[str, list[tuple[str, float]]] = {}
    for start in range(0, n, NEIGHBOUR_BLOCK):
        block = x[start : start + NEIGHBOUR_BLOCK]
        d2 = sq[start : start + len(block), None] + sq[None, :] - 2.0 * (block @ x.T)
        np.maximum(d2, 0.0, out=d2)
        rows = np.arange(len(block))
        d2[rows, start + rows] = np.inf  # not its own neighbour
        part = np.argpartition(d2, k - 1, axis=1)[:, :k]
        for r in range(len(block)):
            order = part[r][np.lexsort((part[r], d2[r, part[r]]))]
            out[ids[start + r]] = [(ids[j], float(np.sqrt(d2[r, j]))) for j in order]
    return out


# Off by default: 20 uuid rows per cell is ~190 MB per weights version, too large
# for the free database tier, and /v1/similar is ~0.15 s on the HNSW index alone.
# Re-enable (SIMILAR_CELLS=1) once neighbours are stored compactly (one int array
# per cell).
WRITE_SIMILAR_CELLS = os.environ.get("SIMILAR_CELLS") == "1"


def write_similar_cells(conn, weights_version: str, neighbours: dict) -> int:
    """Replaces the weights version's rows of similar_cells (migration 0011) in one
    transaction. Returns rows written, or 0 when the table does not exist yet."""
    with conn.cursor() as cur:
        cur.execute("select to_regclass('similar_cells') as t")
        if cur.fetchone()["t"] is None:
            print("similar_cells missing (migration 0011 not applied); skipped.", file=sys.stderr)
            return 0
    written = 0
    try:
        with conn.cursor() as cur:
            cur.execute("delete from similar_cells where weights_version = %s", (weights_version,))
            # executemany, not COPY: common.db connections run in pipeline mode,
            # where COPY is not supported.
            rows = [
                (gid, weights_version, nid, rank, dist)
                for gid, items in neighbours.items()
                for rank, (nid, dist) in enumerate(items, start=1)
            ]
            for start in range(0, len(rows), 5000):
                cur.executemany(
                    "insert into similar_cells "
                    "(geo_entity_id, weights_version, neighbor_id, rank, distance) "
                    "values (%s, %s, %s, %s, %s)",
                    rows[start : start + 5000],
                )
            written = len(rows)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return written


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
        neighbours: dict = {}
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
            if WRITE_SIMILAR_CELLS:
                try:
                    neighbours.update(top_neighbours([g for g, _ in items], [v for _, v in items]))
                except ImportError:
                    print("numpy missing; similar_cells not computed.", file=sys.stderr)
        ctx.rows_affected = total
        if neighbours:
            n = write_similar_cells(conn, SCORING_WEIGHTS_VERSION, neighbours)
            print(f"Wrote {n} similar_cells rows.", file=sys.stderr)

    print(f"Wrote {total} embeddings.", file=sys.stderr)


if __name__ == "__main__":
    run()
