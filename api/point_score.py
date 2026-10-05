"""DB wiring for `precision=point` scoring (GET /v1/score, GET /v1/area): finds the
containing cell(s), runs one live places query for all points, normalizes with the
metro's factor scales and returns plain dicts. The maths is in scoring/point.py
and scoring/scales.py; this file only moves data.

Round trips for a warm request: ONE. The cell lookup and the live places query go
out in the same psycopg pipeline (they do not depend on each other: the live query
uses the geohash centre of the point's cell, which is the stored centroid). Scales
are cached in-process per (weights_version, metro_area).

Scales come from the `score_scales` table (migration 0013, written by
scoring/run.py). Until that table exists/has rows they are computed once per metro
per Lambda instance from feature_store (read-only) with scoring.scales.compute_scales.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import psycopg

from api.areas import AGGREGATE_COLUMNS
from api.lookup import bbox_around, build_score_response, nearest_geo_entity
from api.schemas import ScoreResponse
from common.feature_columns import from_db_row, from_db_rows, new_name
from common.geo import encode as geohash_encode
from scoring.engine import WEIGHTS_VERSION_V2, WEIGHTS_VERSION_V2_1
from scoring.point import (
    DEFAULT_ANCHOR,
    build_point_features,
    execute_live,
    read_live,
)
from scoring.scales import (
    Scales,
    compute_scales,
    scale_feature_columns,
    scales_from_rows,
    score_row,
)

log = logging.getLogger(__name__)

SUPPORTED_VERSIONS = (WEIGHTS_VERSION_V2, WEIGHTS_VERSION_V2_1)


class PointScoringError(Exception):
    """Point scoring is not possible here; the caller serves the grid score."""


@dataclass
class PointResult:
    lat: float
    lon: float
    cell: dict  # geo_entities + feature_store columns of the containing cell
    scores: dict[str, float]  # {score_column: 0-100, ..., 'composite_score'}
    features: dict  # raw feature dict used (point-level values)
    metro_area: str = ""
    timings_ms: dict[str, float] = field(default_factory=dict)


# --- scales ----------------------------------------------------------------------

_SCALES: dict[tuple[str, str], Scales] = {}
_SCALES_SOURCE: dict[tuple[str, str], str] = {}
_SCALES_COLD_MS: dict[tuple[str, str], float] = {}
_LOCK = threading.Lock()


def clear_scales_cache() -> None:
    with _LOCK:
        _SCALES.clear()
        _SCALES_SOURCE.clear()
        _SCALES_COLD_MS.clear()


def scales_info() -> dict:
    """{(version, metro): (source, load_ms)} for diagnostics and the validation report."""
    return {k: (_SCALES_SOURCE[k], _SCALES_COLD_MS.get(k, 0.0)) for k in _SCALES}


def load_scales(conn, weights_version: str, metro_area: str) -> Scales:
    key = (weights_version, metro_area)
    cached = _SCALES.get(key)
    if cached is not None:
        return cached
    with _LOCK:
        cached = _SCALES.get(key)
        if cached is not None:
            return cached
        started = time.perf_counter()
        scales = _scales_from_table(conn, weights_version, metro_area)
        source = "table"
        if not scales:
            scales = _scales_from_feature_store(conn, weights_version, metro_area)
            source = "feature_store"
        if not scales:
            raise PointScoringError(f"no scales for {metro_area}")
        _SCALES[key] = scales
        _SCALES_SOURCE[key] = source
        _SCALES_COLD_MS[key] = (time.perf_counter() - started) * 1000
        return scales


def _scales_from_table(conn, weights_version: str, metro_area: str) -> Scales | None:
    try:
        with conn.cursor() as cur:
            cur.execute(
                "select factor, component, lo, hi, n from score_scales "
                "where weights_version = %s and metro_area = %s",
                (weights_version, metro_area),
            )
            rows = cur.fetchall()
    except psycopg.errors.UndefinedTable:
        conn.rollback()
        return None
    return scales_from_rows(rows) if rows else None


def _scales_from_feature_store(conn, weights_version: str, metro_area: str) -> Scales | None:
    columns = ", ".join(f"fs.{new_name(c)}" for c in scale_feature_columns(weights_version))
    with conn.cursor() as cur:
        cur.execute(
            f"select {columns} from feature_store fs "
            "join geo_entities ge on ge.id = fs.geo_entity_id where ge.metro_area = %s",
            (metro_area,),
        )
        rows = from_db_rows(cur.fetchall())
    return compute_scales(rows, weights_version) if rows else None


# --- cells -------------------------------------------------------------------------

_CELL_COLUMNS = "ge.id, ge.geohash, ge.latitude, ge.longitude, ge.formatted_address, ge.metro_area"
CELL_SQL = (
    "select {cols}, f.* from geo_entities ge join feature_store f on f.geo_entity_id = ge.id "
    "where ge.geohash = any(%s)"
)


def _cell_query(with_neighborhood: bool) -> str:
    cols = _CELL_COLUMNS + (", ge.neighborhood" if with_neighborhood else "")
    return CELL_SQL.format(cols=cols)


def _fetch_cells(conn, geohashes: list[str]) -> dict[str, dict]:
    with conn.cursor() as cur:
        cur.execute(_cell_query(True), (geohashes,))
        return {r["geohash"]: from_db_row(r) for r in cur.fetchall()}


def _nearest_cell(conn, lat: float, lon: float) -> dict | None:
    min_lat, max_lat, min_lon, max_lon = bbox_around(lat, lon)
    with conn.cursor() as cur:
        cur.execute(
            "select geohash, latitude, longitude from geo_entities "
            "where latitude between %s and %s and longitude between %s and %s",
            (min_lat, max_lat, min_lon, max_lon),
        )
        candidates = cur.fetchall()
    near = nearest_geo_entity(lat, lon, candidates)
    if near is None:
        return None
    return _fetch_cells(conn, [near["geohash"]]).get(near["geohash"])


def fetch_cell(conn, lat: float, lon: float, geohash: str) -> dict | None:
    """The cell (geo_entities + feature_store row) under a point: exact geohash6, else the
    nearest cell (the same fallback as GET /v1/score)."""
    return _fetch_cells(conn, [geohash]).get(geohash) or _nearest_cell(conn, lat, lon)


# --- scoring -----------------------------------------------------------------------


def score_points(
    conn,
    points: list[tuple[float, float]],
    weights_version: str,
    anchor: frozenset[str] = DEFAULT_ANCHOR,
) -> list[PointResult]:
    return score_points_cells(conn, points, weights_version, anchor)[0]


def score_points_cells(
    conn,
    points: list[tuple[float, float]],
    weights_version: str,
    anchor: frozenset[str] = DEFAULT_ANCHOR,
    extra_geohashes: tuple[str, ...] = (),
) -> tuple[list[PointResult], dict[str, dict]]:
    """score_points, plus the cell rows (geo_entities + feature_store) of every sample
    point's geohash and of `extra_geohashes`, fetched by the SAME cell query (no extra
    round trip). Scores each (lat, lon) at its exact position. Raises PointScoringError when a
    point has no containing/nearby cell, the version is unsupported or anything else
    prevents it (the caller then serves the grid score)."""
    if weights_version not in SUPPORTED_VERSIONS:
        raise PointScoringError(f"unsupported weights version {weights_version!r}")
    t0 = time.perf_counter()
    geohashes = [geohash_encode(lat, lon, precision=6) for lat, lon in points]
    live_points = [(g, lat, lon) for g, (lat, lon) in zip(geohashes, points, strict=True)]

    try:
        with conn.cursor() as cell_cur, conn.cursor() as live_cur:
            cell_cur.execute(_cell_query(True), (sorted({*geohashes, *extra_geohashes}),))
            execute_live(live_cur, live_points, anchor)
            cells = {r["geohash"]: from_db_row(r) for r in cell_cur.fetchall()}
            live = read_live(live_cur)
    except psycopg.errors.UndefinedColumn:  # neighborhood column (migration 0008) missing
        conn.rollback()
        raise PointScoringError("schema missing neighborhood column") from None
    t_query = time.perf_counter()

    results: list[PointResult] = []
    for i, (lat, lon) in enumerate(points):
        cell, index, point_live = cells.get(geohashes[i]), i, live
        if cell is None:
            # No cell under this geohash: use the nearest one, and redo this point's
            # live query against that cell's centroid.
            cell = _nearest_cell(conn, lat, lon)
            if cell is None:
                raise PointScoringError("no cell near this point")
            with conn.cursor() as cur:
                execute_live(cur, [(cell["geohash"], lat, lon)], anchor)
                point_live, index = read_live(cur), 0
        scales = load_scales(conn, weights_version, cell["metro_area"])
        features = build_point_features(cell, lat, lon, point_live, index, anchor).row
        scores = score_row(features, weights_version, scales)
        if not scores:
            raise PointScoringError("no factor has data at this point")
        results.append(PointResult(lat, lon, cell, scores, features, cell["metro_area"]))
    done = time.perf_counter()
    for r in results:
        r.timings_ms = {"query": (t_query - t0) * 1000, "total": (done - t0) * 1000}
    return results, cells


# --- responses -----------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def point_score_response(result: PointResult, weights_version: str) -> ScoreResponse:
    """ScoreResponse for one on-demand point: sub-scores and composite from the point's
    own raw features; ids, neighborhood and school district from its containing cell."""
    cell = result.cell
    score_row = {**result.scores, "weights_version": weights_version, "computed_at": _now()}
    geo_entity = {
        "id": cell["id"],
        "latitude": result.lat,
        "longitude": result.lon,
        "formatted_address": None,
        "neighborhood": cell.get("neighborhood"),
    }
    response = build_score_response(geo_entity, score_row, {**cell, **result.features})
    return response.model_copy(update={"precision": "point"})


def area_aggregate_from_points(results: list[PointResult], weights_version: str) -> dict:
    """The dict api.areas.build_area_response expects, with each column the equal-weight
    mean of the sample points that have it (a point with a null factor drops out of
    that factor's mean, like the grid aggregate); composite is the mean of composites."""
    aggregate: dict = {}
    for column in AGGREGATE_COLUMNS:
        values = [r.scores[column] for r in results if r.scores.get(column) is not None]
        aggregate[column] = sum(values) / len(values) if values else None
    aggregate["cell_count"] = len({str(r.cell["id"]) for r in results})
    aggregate["computed_at"] = _now()
    aggregate["weights_version"] = weights_version
    return aggregate
