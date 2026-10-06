"""Stored per-area scores for density weights versions (migration 0023, scoring/area_run.py).

A density version (v2.2-density) scores each road-bounded area once, offline, from routed
travel times; GET /v1/area serves the stored row instead of scoring sample points on demand.
The row has the same keys as a `scores` row, so the existing response builders take it as is.
"""

from __future__ import annotations

from scoring.engine import DENSITY_VERSIONS

AREA_SCORES_SQL = """
select a.*, 1 as cell_count
from area_scores a
where a.area_id = %s and a.weights_version = %s
"""


def is_density(weights_version: str) -> bool:
    return weights_version in DENSITY_VERSIONS


def fetch(conn, area_id: int, weights_version: str) -> dict | None:
    """The area's stored scores, or None when it has none (or the table is missing)."""
    import psycopg

    try:
        with conn.cursor() as cur:
            cur.execute(AREA_SCORES_SQL, (area_id, weights_version))
            row = cur.fetchone()
    except psycopg.errors.UndefinedTable:
        conn.rollback()
        return None
    if row is None or row.get("composite_score") is None:
        return None
    return dict(row)
