"""Pure, DB-free geo-lookup and response-shape-building helpers for
GET /score. Kept separate from api/main.py's route handler so the parts
worth unit testing without a live Postgres connection (bbox math,
nearest-neighbor fallback, mapping a `scores` row onto the SubScores
response shape) are plain functions over dicts -- see tests/test_api.py.
"""

from api.schemas import ScoreResponse, SubScores
from common.geo import haversine_m
from scoring.engine import CATEGORY_SPECS

# Fallback bounding-box half-width in degrees, used when the exact
# geohash6 cell (encoded the same way ingestion/grid.py builds the grid)
# has no geo_entities row. geohash6 cells are ~1.22km x 0.61km
# (ingestion/grid.py), so ~0.03 deg comfortably covers the cell's
# immediate neighbors in every direction. Cheap to scan: the whole metro
# is only ~64k geo_entities rows total (PROJECT.md/PHASES.md), so even an
# unindexed-feeling bbox scan plus a Python nearest-neighbor pass is fine
# without reaching for PostGIS.
FALLBACK_BBOX_MARGIN_DEG = 0.03


def bbox_around(
    lat: float, lon: float, margin_deg: float = FALLBACK_BBOX_MARGIN_DEG
) -> tuple[float, float, float, float]:
    """Returns (min_lat, max_lat, min_lon, max_lon) for the fallback bbox
    query when the exact geohash6 cell misses."""
    return (lat - margin_deg, lat + margin_deg, lon - margin_deg, lon + margin_deg)


def nearest_geo_entity(lat: float, lon: float, candidates: list[dict]) -> dict | None:
    """Picks the closest candidate (each dict needs 'latitude'/'longitude')
    by haversine distance. `candidates` is expected to be the bbox result
    set -- ~a handful to a few hundred rows, cheap to scan in Python."""
    if not candidates:
        return None
    return min(candidates, key=lambda c: haversine_m(lat, lon, c["latitude"], c["longitude"]))


def sub_scores_from_score_row(score_row: dict) -> SubScores:
    """Maps `scores` table columns (grocery_score, gas_station_score, ...)
    onto the SubScores response shape (grocery, gas_station -> gasStation
    on the wire via CamelModel's alias_generator) using
    scoring.engine.CATEGORY_SPECS as the single source of truth for the
    column-name -> field-name mapping (strip the '_score' suffix)."""
    fields = {}
    for spec in CATEGORY_SPECS:
        field_name = spec.score_column.removesuffix("_score")
        fields[field_name] = score_row.get(spec.score_column)
    return SubScores(**fields)


def build_score_response(geo_entity: dict, score_row: dict) -> ScoreResponse:
    """Pure response builder from plain dict rows (psycopg's dict_row
    cursor output, or a hand-built dict in tests) -- no DB access here.
    `geo_entity` needs id/latitude/longitude/formatted_address;
    `score_row` needs composite_score/weights_version/computed_at plus the
    *_score columns SubScores reads."""
    address = geo_entity.get("formatted_address") or (
        f"{geo_entity['latitude']:.5f},{geo_entity['longitude']:.5f}"
    )
    return ScoreResponse(
        geo_entity_id=geo_entity["id"],
        address=address,
        latitude=geo_entity["latitude"],
        longitude=geo_entity["longitude"],
        composite_score=score_row["composite_score"],
        sub_scores=sub_scores_from_score_row(score_row),
        weights_version=score_row["weights_version"],
        computed_at=score_row["computed_at"],
    )
