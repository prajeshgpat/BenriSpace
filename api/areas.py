"""Pure helpers for GET /v1/area: which road-bounded area contains a click,
and how an area's score is aggregated from the geohash6 cells it overlaps.

No DB access here; common/db.py runs the SQL built by `aggregate_sql`.
"""

import math
from datetime import datetime
from itertools import pairwise

from api.explain import build_explanation, nearest_m_by_factor
from api.lookup import school_info_from_rows, sub_scores_from_score_row
from api.schemas import AreaInfo, AreaScoreResponse
from scoring.engine import CATEGORY_SPECS

# Mirrors ingestion/areas/limits.py (MAX_AREA_SQ_MI, MAX_EXTENT_MI); a test
# asserts they stay equal. Areas built before the size limits (or with a
# non-null extent_m above the cap) are treated as not found.
AREA_MAX_SQ_MI = 0.8
AREA_MAX_EXTENT_MI = 1.4
SQ_M_PER_SQ_MI = 2_589_988.11
M_PER_MI = 1609.344
SNAP_M = 40.0
_EARTH_R = 6_371_008.8

# Every aggregated column: the 13 factor scores (plus their v2 legacy columns), the informational school
# proximity score, and the composite. Order is the SELECT order.
FACTOR_COLUMNS: list[str] = [s.score_column for s in CATEGORY_SPECS]
EXTRA_COLUMNS: list[str] = [
    s.proximity_score_column for s in CATEGORY_SPECS if s.proximity_score_column
]
AGGREGATE_COLUMNS: list[str] = [*FACTOR_COLUMNS, *EXTRA_COLUMNS, "composite_score"]


# --- geometry ----------------------------------------------------------------


def _polygons(geometry: dict) -> list[list[list[list[float]]]]:
    kind = geometry.get("type")
    if kind == "Polygon":
        return [geometry["coordinates"]]
    if kind == "MultiPolygon":
        return list(geometry["coordinates"])
    return []


def _in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def point_in_polygon(lon: float, lat: float, geometry: dict) -> bool:
    """Ray casting over a GeoJSON Polygon/MultiPolygon ([lon, lat]). The first
    ring of each polygon is the shell, later rings are holes."""
    for rings in _polygons(geometry):
        if not rings or not _in_ring(lon, lat, rings[0]):
            continue
        if any(_in_ring(lon, lat, hole) for hole in rings[1:]):
            continue
        return True
    return False


def _dist_to_segment_m(lon, lat, a, b) -> float:
    # Local equirectangular projection around the point; fine at 40 m scale.
    kx = math.cos(math.radians(lat)) * math.pi / 180 * _EARTH_R
    ky = math.pi / 180 * _EARTH_R
    ax, ay = (a[0] - lon) * kx, (a[1] - lat) * ky
    bx, by = (b[0] - lon) * kx, (b[1] - lat) * ky
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    t = 0.0 if seg2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / seg2))
    return math.hypot(ax + t * dx, ay + t * dy)


def distance_to_polygon_m(lon: float, lat: float, geometry: dict) -> float:
    """Metres from the point to the nearest ring segment (shell or hole)."""
    best = math.inf
    for rings in _polygons(geometry):
        for ring in rings:
            for a, b in pairwise(ring):
                best = min(best, _dist_to_segment_m(lon, lat, a, b))
    return best


def area_too_big(area: dict) -> bool:
    """True when the area breaks the size caps: over AREA_MAX_SQ_MI, or
    (when extent_m is known) longer than AREA_MAX_EXTENT_MI across."""
    if area["area_sq_m"] / SQ_M_PER_SQ_MI > AREA_MAX_SQ_MI:
        return True
    extent = area.get("extent_m")
    return extent is not None and extent / M_PER_MI > AREA_MAX_EXTENT_MI


def usable_areas(candidates: list[dict]) -> list[dict]:
    """Candidates within the size caps (filter BEFORE pick_area, so an
    oversized legacy polygon can neither win nor be snapped to)."""
    return [c for c in candidates if not area_too_big(c)]


def pick_area(lat: float, lon: float, candidates: list[dict], snap_m: float = SNAP_M) -> dict | None:
    """The candidate (needs 'geometry', 'area_sq_m') containing the point; the
    smallest wins when several do. Otherwise the nearest candidate within
    `snap_m` metres of its boundary (a click on the road line itself), else None."""
    containing = [c for c in candidates if point_in_polygon(lon, lat, c["geometry"])]
    if containing:
        return min(containing, key=lambda c: c["area_sq_m"])
    best, best_d = None, snap_m
    for c in candidates:
        d = distance_to_polygon_m(lon, lat, c["geometry"])
        if d <= best_d:
            best, best_d = c, d
    return best


# --- aggregation -------------------------------------------------------------


def aggregate_sql() -> str:
    """SQL (params: weights_version, area_id) giving one row for an area.

    Each cell uses its LATEST scores row, preferring `weights_version` exactly
    like common.db.get_latest_score. Per column the result is
    sum(score * overlap_sq_m) / sum(overlap_sq_m where score is not null): a
    cell with NULL for a factor drops out of that factor's numerator and
    denominator. `composite_score` is the area-weighted mean of the cells'
    stored composites, so it equals the average of what the map shows and may
    differ slightly from recomputing a composite from the averaged sub-scores
    (null factors are skipped per cell there, per area here). `cell_count`
    counts cells that have a score row; `computed_at` is the newest of them.
    """
    cols = ",\n            ".join(
        f"(sum(s.{c}::float8 * ac.overlap_sq_m) / "
        f"nullif(sum(ac.overlap_sq_m) filter (where s.{c} is not null), 0)) as {c}"
        for c in AGGREGATE_COLUMNS
    )
    return f"""
        select
            {cols},
            count(*) as cell_count,
            max(s.computed_at) as computed_at,
            max(s.weights_version) as weights_version
        from area_cells ac
        join geo_entities ge on ge.geohash = ac.geohash
        join lateral (
            select *
            from scores s2
            where s2.geo_entity_id = ge.id
            order by (s2.weights_version = %s) desc nulls last, s2.computed_at desc
            limit 1
        ) s on true
        where ac.area_id = %s
    """


def aggregate_cells(cells: list[dict]) -> dict:
    """Reference implementation of `aggregate_sql` over plain dicts (each with
    'overlap_sq_m' and score columns). Used by tests; the route uses SQL."""
    out: dict = {}
    for col in AGGREGATE_COLUMNS:
        pairs = [(c[col], c["overlap_sq_m"]) for c in cells if c.get(col) is not None]
        den = sum(w for _, w in pairs)
        out[col] = sum(v * w for v, w in pairs) / den if den else None
    out["cell_count"] = len(cells)
    return out


# --- response ----------------------------------------------------------------


def bounded_by_text(names: list[str]) -> str:
    names = [n for n in names if n][:4]
    if not names:
        return "Area bounded by major roads"
    if len(names) == 1:
        return f"Area bounded by {names[0]}"
    return f"Area bounded by {', '.join(names[:-1])} and {names[-1]}"


def area_explanation(sub_scores, feature_row: dict | None, priorities: list[str] | None = None) -> str:
    text = build_explanation(sub_scores, nearest_m_by_factor(feature_row), priorities)
    text = text.replace("This location's", "This area's", 1)
    return text.replace("Nearest feature:", "Nearest feature from this spot:")


def build_area_response(
    area: dict,
    aggregate: dict,
    geo_entity: dict,
    lat: float,
    lon: float,
    feature_row: dict | None,
    weights_version: str,
) -> AreaScoreResponse:
    sub_scores = sub_scores_from_score_row(aggregate)
    names = list(area.get("bounded_by") or [])
    computed_at = aggregate["computed_at"]
    assert isinstance(computed_at, datetime)
    return AreaScoreResponse(
        geo_entity_id=geo_entity["id"],
        address=bounded_by_text(names),
        latitude=lat,
        longitude=lon,
        composite_score=float(aggregate["composite_score"]),
        sub_scores=sub_scores,
        weights_version=aggregate.get("weights_version") or weights_version,
        computed_at=computed_at,
        school=school_info_from_rows(aggregate, feature_row),
        neighborhood=area.get("neighborhood") or (geo_entity or {}).get("neighborhood"),
        area_id=area["id"],
        area=AreaInfo(
            geometry=area["geometry"],
            area_sq_mi=area["area_sq_m"] / SQ_M_PER_SQ_MI,
            bounded_by=names,
            cell_count=int(aggregate["cell_count"]),
        ),
        explanation=area_explanation(sub_scores, feature_row),
    )
