"""Bounding-box prefiltered read for POST /v1/triangulate.

common.db.iter_latest_scored_geo_entities loads every scored cell (~64k
rows); the circles only ever need the cells near them. This module adds a
lat/lon range prefilter derived from the anchor circles. It is a pure
superset filter: api.triangulate.rank_candidates still applies the exact
haversine membership test, so results are identical.
"""

import math
from collections.abc import Sequence

from api.triangulate import AnchorCircle
from common.geo import EARTH_RADIUS_M

BBOX_PAD = 1.01  # slack so rounding never drops a cell on the circle edge
_M_PER_DEG_LAT = math.pi * EARTH_RADIUS_M / 180.0

LatLonBox = tuple[float, float, float, float]  # min_lat, max_lat, min_lon, max_lon


def circle_bbox(circle: AnchorCircle) -> LatLonBox | None:
    """Lat/lon box containing the circle; the lon range is None-ed out (full
    range) when the circle reaches a pole or would wrap the antimeridian."""
    d_lat = circle.radius_m / _M_PER_DEG_LAT * BBOX_PAD
    min_lat, max_lat = circle.latitude - d_lat, circle.latitude + d_lat
    widest_lat = max(abs(min_lat), abs(max_lat))
    if widest_lat >= 89.0:
        return (max(min_lat, -90.0), min(max_lat, 90.0), -180.0, 180.0)
    d_lon = d_lat / math.cos(math.radians(widest_lat))
    min_lon, max_lon = circle.longitude - d_lon, circle.longitude + d_lon
    if min_lon < -180.0 or max_lon > 180.0:
        min_lon, max_lon = -180.0, 180.0
    return (max(min_lat, -90.0), min(max_lat, 90.0), min_lon, max_lon)


def combined_bbox(circles: Sequence[AnchorCircle], combine_mode: str) -> LatLonBox | None:
    """Box covering every cell that could match: the union of the circle
    boxes for "union", their intersection for "intersect". None means no
    prefilter (no circles); an inverted/empty box is returned as-is so the
    caller can short-circuit."""
    if not circles:
        return None
    boxes = [circle_bbox(c) for c in circles]
    if combine_mode == "union":
        return (
            min(b[0] for b in boxes),
            max(b[1] for b in boxes),
            min(b[2] for b in boxes),
            max(b[3] for b in boxes),
        )
    return (
        max(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        min(b[3] for b in boxes),
    )


def box_is_empty(box: LatLonBox) -> bool:
    return box[0] > box[1] or box[2] > box[3]


_SQL = """
    select distinct on (s.geo_entity_id)
        s.geo_entity_id, s.composite_score, s.weights_version, s.computed_at,
        ge.formatted_address, ge.latitude, ge.longitude
    from scores s
    join geo_entities ge on ge.id = s.geo_entity_id
    {where}
    order by s.geo_entity_id, (s.weights_version = %s) desc nulls last, s.computed_at desc
"""


def build_candidates_sql(
    box: LatLonBox | None, weights_version: str | None = None
) -> tuple[str, list]:
    if box is None:
        return _SQL.format(where=""), [weights_version]
    where = "where ge.latitude between %s and %s and ge.longitude between %s and %s"
    return _SQL.format(where=where), [*box, weights_version]


def get_scored_candidates_in_box(
    conn, box: LatLonBox | None, weights_version: str | None = None
) -> list[dict]:
    """Latest score per geo_entity (same columns/semantics as
    common.db.iter_latest_scored_geo_entities) restricted to `box`."""
    if box is not None and box_is_empty(box):
        return []
    sql, params = build_candidates_sql(box, weights_version)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [dict(row) for row in cur]
